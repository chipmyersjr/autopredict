from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, func, delete, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from app.main import app
from app.models import Bet, Game, Run, RunGame, Selection, Strategy, User
from app.schemas import RunCreate
from app.seed import demo_games, seed_demo
from app.seed_strategy import seed_strategy, RANDOM_STRATEGY_ID
from app.seed_user import seed_user, LOCAL_USER_ID
import asyncio
from app.predictors import RandomPredictor
from app.run_worker import claim_next, process_claim
from test_strategies import NOW, Pick

@pytest.fixture
def api(migrated_database, monkeypatch):
    engine, _ = migrated_database
    seed_user(engine); seed_strategy(engine)
    games = demo_games(date(2026, 10, 1))
    for g in games: g.start_time = NOW + timedelta(days=1)
    seed_demo(engine, games)
    monkeypatch.setattr('app.main.create_database_engine', lambda settings: engine)
    monkeypatch.setattr('app.runs.utc_now', lambda: NOW)
    monkeypatch.setattr('app.run_worker.db_now', lambda session: NOW)
    with TestClient(app) as client:
        client.test_engine = engine
        yield client, engine, games

def body(games):
    return dict(strategy_id=str(RANDOM_STRATEGY_ID), game_ids=[str(g.id) for g in games], starting_bankroll='40.00', stake_per_bet='10.00')

def post(client, payload, key=None):
    return client.post('/api/runs', json=payload, headers={'Idempotency-Key':str(key or uuid4())})


def drain(engine):
    while (claim := claim_next(engine)) is not None:
        asyncio.run(process_claim(engine, claim, lambda *_: RandomPredictor(Pick(0))))


def finished_post(client, payload, key=None):
    key = key or uuid4()
    response = post(client, payload, key)
    if response.status_code in (200, 201):
        drain(client.test_engine)
        return post(client, payload, key)
    return response


def legacy_execution_fixture(engine):
    """Represent pre-worker records for historical migration-cycle tests only."""
    with engine.begin() as connection:
        connection.execute(text('UPDATE runs SET execution_generation=0'))
        connection.execute(text('UPDATE run_games SET attempts=0, prediction_input=NULL, validated_prediction=NULL'))

@pytest.mark.parametrize('value',['NaN','Infinity','0','-1','1.001','10000000000.00',10,'1e2',True])
def test_money(value):
    with pytest.raises(ValidationError): RunCreate(**{**body([MagicMock(id=uuid4())]), 'stake_per_bet':value})

def test_create_reload_replay_snapshot(api):
    client, engine, games = api
    key=uuid4(); payload=body(list(reversed(games)))
    response=post(client,payload,key)
    assert response.status_code == 201, response.text
    accepted=response.json()
    assert accepted['run']['execution_status']=='queued' and accepted['bets']==[]
    assert post(client,payload,key).json()==accepted
    assert client.post('/api/runs/'+accepted['run']['id']+'/settle').status_code==409
    drain(engine)
    saved=post(client,payload,key).json(); run=saved['run']
    assert run['execution_status']=='completed'
    assert run['game_ids']==payload['game_ids'] and run['bet_count']==4
    assert run['committed_stake']=='40.00' and run['available_bankroll']=='0.00'
    assert run['final_bankroll'] is run['total_profit'] is run['roi'] is run['end_time'] is None
    assert len(saved['skipped_games'])==1
    assert [b['game_id'] for b in saved['bets']]==payload['game_ids'][1:]
    assert all(b['price']=='1.9091' and b['status']=='open' and b['result'] is b['profit'] is b['settled_at'] is b['quote_provenance'] is None for b in saved['bets'])
    with Session(engine) as s:
        s.get(User, LOCAL_USER_ID).name='Edited'
        for g in s.scalars(select(Game)): g.start_time=NOW; g.home_team='Changed'
        for selection in s.scalars(select(Selection)): selection.price=Decimal('2.5'); selection.line=Decimal('0')
        s.get(Strategy,RANDOM_STRATEGY_ID).is_active=False
        s.commit()
    assert not seed_user(engine)
    with Session(engine) as s: assert s.get(User,LOCAL_USER_ID).name=='Edited'
    with TestClient(app) as restarted:
        replay=post(restarted,{**payload,'starting_bankroll':'40'},key)
        assert replay.status_code==200 and replay.json()==saved
        assert restarted.get('/api/runs').json()==[run]
        assert restarted.get('/api/runs/'+run['id']).json()==run
        assert restarted.get('/api/runs/'+run['id']+'/bets').json()==saved['bets']
        for b in saved['bets']: assert restarted.get('/api/bets/'+b['id']).json()==b
    assert post(client,{**payload,'notes':'different'},key).status_code==409

def test_atomic_failures(api,monkeypatch):
    client,engine,games=api
    generator=MagicMock(); monkeypatch.setattr('app.predictors.RandomPredictor.predict',generator)
    assert post(client,{**body(games),'starting_bankroll':'39.99'}).status_code==422
    assert post(client,body([games[-1]])).status_code==409
    assert post(client,{**body(games),'game_ids':[str(games[0].id),str(uuid4())]}).status_code==404
    assert post(client,{**body(games),'strategy_id':str(uuid4())}).status_code==404
    generator.assert_not_called()
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Run))==0
        assert s.scalar(select(func.count()).select_from(Bet))==0
    for changes in [{'game_ids':[]},{'game_ids':[str(games[0].id)]*2},{'name':' '},{'user_id':str(uuid4())}]:
        assert post(client,{**body(games),**changes}).status_code==422
    assert client.post('/api/runs',json=body(games)).status_code==422
    assert client.post('/api/runs',json=body(games),headers={'Idempotency-Key':'bad'}).status_code==422
    for path in ['/api/runs/','/api/bets/']:
        assert client.get(path+'bad').status_code==422
        assert client.get(path+str(uuid4())).status_code==404
    assert client.get('/api/runs').json()==[]
    assert client.options('/api/runs',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,idempotency-key'}).status_code==200

def test_cutoff_and_adapter_rollback(api,monkeypatch):
    client,engine,games=api
    response=post(client,body(games))
    key=uuid4()
    accepted=post(client,body(games),key).json()
    def fail(*args): raise OperationalError(None,None,Exception('secret'))
    monkeypatch.setattr('app.runs.DryRunAdapter.record',fail)
    with pytest.raises(OperationalError): drain(engine)
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Run))==2
        assert s.scalar(select(func.count()).select_from(Bet))==0
    assert post(client,body(games),key).json()['run']['id']==accepted['run']['id']

def test_concurrent_retry_and_separate_simulation(api):
    client,engine,games=api; key=uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(lambda _:post(client,body(games),key),range(2)))
    assert sorted(r.status_code for r in responses)==[200,201]
    assert responses[0].json()==responses[1].json()
    assert post(client,body(games)).status_code==201
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Run))==2
        assert s.scalar(select(func.count()).select_from(Bet))==0
    drain(engine)
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Bet))==8

def test_ownership_retention(api):
    client,engine,games=api; saved=finished_post(client,body(games)).json()
    with Session(engine) as s:
        from uuid import UUID
        run=s.get(Run,UUID(saved['run']['id']))
        s.add(RunGame(run_id=run.id,game_id=games[0].id,position=99,included_at=NOW))
        with pytest.raises(IntegrityError): s.commit()
        s.rollback()
        for model,ident in [(User,LOCAL_USER_ID),(Strategy,RANDOM_STRATEGY_ID),(Game,games[0].id),(Run,run.id),(Selection,UUID(saved['bets'][0]['selection_id']))]:
            with pytest.raises(IntegrityError): s.execute(delete(model).where(model.id==ident)); s.commit()
            s.rollback()
        owner=User(email='other@example.local',name='Other'); s.add(owner); s.flush(); run.user_id=owner.id; s.commit()
    assert client.get('/api/runs').json()==[]
    for path in ['/api/runs/'+saved['run']['id'],'/api/runs/'+saved['run']['id']+'/bets','/api/bets/'+saved['bets'][0]['id']]: assert client.get(path).status_code==404
    with Session(engine) as s: s.execute(delete(User).where(User.id==LOCAL_USER_ID)); s.commit()
    assert client.get('/api/runs').status_code==503

def test_quote_lock(api,monkeypatch):
    import threading
    from app.runs import DryRunAdapter
    client,engine,games=api
    locked=threading.Event(); started=threading.Event(); done=threading.Event(); original=DryRunAdapter.record
    def recording(*args):
        locked.set(); assert started.wait(2); assert not done.wait(.15)
        return original(*args)
    monkeypatch.setattr(DryRunAdapter,'record',recording)
    def writer():
        assert locked.wait(2)
        with Session(engine) as s:
            selection=s.get(Selection,games[0].markets[0].selections[0].id); selection.price=Decimal('3'); started.set(); s.commit()
        done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(writer); response=finished_post(client,body(games)); future.result(timeout=5)
    assert response.status_code==200 and done.is_set()
    assert all(b['price']=='1.9091' for b in response.json()['bets'])


def test_zero_spread_mixed_cutoff_and_invalid_pair(api, monkeypatch):
    client, engine, games = api
    with Session(engine) as s:
        for selection in s.scalars(select(Selection).where(Selection.market_id==games[0].markets[0].id)):
            selection.line=Decimal('0.00')
        s.get(Game,games[1].id).start_time=NOW+timedelta(seconds=1)
        s.get(Selection,games[2].markets[0].selections[0].id).is_active=False
        s.get(Game,games[3].id).status='canceled'
        s.commit()
    key=uuid4()
    assert post(client,body(games),key).status_code==201
    monkeypatch.setattr('app.run_worker.db_now',lambda session:NOW+timedelta(seconds=1))
    response=finished_post(client,body(games),key)
    assert response.status_code==200
    saved=response.json()
    assert len(saved['bets'])==1 and saved['bets'][0]['line']=='0.00'
    assert [x['reason'] for x in saved['skipped_games']]==['kickoff_reached','spread_unavailable','game_not_scheduled','spread_unavailable']
    assert saved['run']['available_bankroll']=='30.00'


def test_unique_key_conflict_across_strategies(api):
    client,engine,games=api
    second=client.post('/api/strategies',json={'name':'Second'}).json()['id']
    key=uuid4()
    payloads=[body(games),{**body(games),'strategy_id':second}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda payload:post(client,payload,key),payloads))
    assert sorted(r.status_code for r in responses)==[201,409]
    with Session(engine) as s: assert s.scalar(select(func.count()).select_from(Run))==1


def test_history_query_count_and_order(api):
    from sqlalchemy import event
    client,engine,games=api
    saved=[post(client,body(games)).json()['run'] for _ in range(3)]
    statements=[]
    def capture(conn,cursor,statement,parameters,context,many): statements.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:
        response=client.get('/api/runs')
        assert response.status_code==200
        assert len(statements)==4  # owner, Runs, associations, Bets; independent of count
        assert [r['id'] for r in response.json()]==sorted(r['id'] for r in saved)
    finally: event.remove(engine,'before_cursor_execute',capture)


@pytest.mark.parametrize('path',['/api/runs','/api/runs/'+str(uuid4()),'/api/runs/'+str(uuid4())+'/bets','/api/bets/'+str(uuid4())])
def test_sanitized_read_failure(monkeypatch,path):
    session=MagicMock(); session.get.side_effect=OperationalError(None,None,Exception('secret'))
    context=MagicMock(); context.__enter__.return_value=session
    monkeypatch.setattr('app.database.Session',lambda engine:context)
    monkeypatch.setattr('app.main.create_database_engine',lambda settings:MagicMock())
    with TestClient(app) as client:
        response=client.get(path)
        assert response.status_code==503 and response.json()=={'detail':'Database unavailable'}
    session.rollback.assert_called_once()


def test_live_http_persistence_smoke(api, monkeypatch):
    """Actual HTTP server against the fixture's dedicated migrated demo database."""
    import socket
    import threading
    import time
    import httpx
    import uvicorn
    client,engine,games=api
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True); thread.start()
    try:
        deadline=time.monotonic()+5
        while not server.started and time.monotonic()<deadline: time.sleep(.01)
        assert server.started
        with httpx.Client(base_url=f'http://127.0.0.1:{port}') as http:
            key=str(uuid4()); headers={'Idempotency-Key':key}
            created=http.post('/api/runs',json=body(games),headers=headers)
            assert created.status_code==201
            assert created.json()['bets']==[]
            drain(engine)
            saved=http.post('/api/runs',json=body(games),headers=headers).json(); ident=saved['run']['id']
            replay=http.post('/api/runs',json=body(games),headers=headers)
            assert replay.status_code==200 and replay.json()==saved
            assert http.get('/api/runs').json()==[saved['run']]
            assert http.get('/api/runs/'+ident).json()==saved['run']
            assert http.get('/api/runs/'+ident+'/bets').json()==saved['bets']
            assert http.get('/api/bets/'+saved['bets'][0]['id']).json()==saved['bets'][0]
    finally:
        server.should_exit=True; thread.join(timeout=5)
        assert not thread.is_alive()


def test_openapi_contract():
    schema=app.openapi()
    creation=schema['paths']['/api/runs']['post']
    assert creation['responses']['200']['content']['application/json']['schema']==creation['responses']['201']['content']['application/json']['schema']
    assert any(p['name']=='Idempotency-Key' and p['required'] and p['schema']['format']=='uuid' for p in creation['parameters'])
    assert schema['components']['schemas']['RunCreate']['additionalProperties'] is False

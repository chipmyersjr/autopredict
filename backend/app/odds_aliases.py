"""Explicit NCAAF provider labels → CFBD school identities.

This is an exact lookup catalog, not a suffix stripper or fuzzy matcher. Only
persisted FBS CFBD identities authorize season-scoped aliases. New/unrecognized
provider spellings require a catalog update; existing records are never replaced.
Provider naming reference: https://the-odds-api.com/sports/ncaaf-odds.html
CFBD identity reference: https://api.collegefootballdata.com/api/teams
"""

from collections import defaultdict

from sqlalchemy import select

from app.models import TeamAlias


# Values are explicit CFBD school-name spellings, including known alternatives.
ODDS_TEAMS = {
    "Air Force Falcons": ("Air Force",),
    "Akron Zips": ("Akron",),
    "Alabama Crimson Tide": ("Alabama",),
    "Appalachian State Mountaineers": ("App State", "Appalachian State"),
    "Arizona Wildcats": ("Arizona",),
    "Arizona State Sun Devils": ("Arizona State",),
    "Arkansas Razorbacks": ("Arkansas",),
    "Arkansas State Red Wolves": ("Arkansas State",),
    "Army Black Knights": ("Army",),
    "Auburn Tigers": ("Auburn",),
    "Ball State Cardinals": ("Ball State",),
    "Baylor Bears": ("Baylor",),
    "Boise State Broncos": ("Boise State",),
    "Boston College Eagles": ("Boston College",),
    "Bowling Green Falcons": ("Bowling Green",),
    "Buffalo Bulls": ("Buffalo",),
    "BYU Cougars": ("BYU",),
    "California Golden Bears": ("California",),
    "Central Michigan Chippewas": ("Central Michigan",),
    "Charlotte 49ers": ("Charlotte",),
    "Cincinnati Bearcats": ("Cincinnati",),
    "Clemson Tigers": ("Clemson",),
    "Coastal Carolina Chanticleers": ("Coastal Carolina",),
    "Colorado Buffaloes": ("Colorado",),
    "Colorado State Rams": ("Colorado State",),
    "Connecticut Huskies": ("UConn", "Connecticut"),
    "UConn Huskies": ("UConn", "Connecticut"),
    "Delaware Blue Hens": ("Delaware",),
    "Duke Blue Devils": ("Duke",),
    "East Carolina Pirates": ("East Carolina",),
    "Eastern Michigan Eagles": ("Eastern Michigan",),
    "Florida Gators": ("Florida",),
    "Florida Atlantic Owls": ("Florida Atlantic",),
    "Florida International Panthers": ("Florida International", "FIU"),
    "FIU Panthers": ("Florida International", "FIU"),
    "Florida State Seminoles": ("Florida State",),
    "Fresno State Bulldogs": ("Fresno State",),
    "Georgia Bulldogs": ("Georgia",),
    "Georgia Southern Eagles": ("Georgia Southern",),
    "Georgia State Panthers": ("Georgia State",),
    "Georgia Tech Yellow Jackets": ("Georgia Tech",),
    "Hawaii Rainbow Warriors": ("Hawai'i", "Hawaii"),
    "Houston Cougars": ("Houston",),
    "Illinois Fighting Illini": ("Illinois",),
    "Indiana Hoosiers": ("Indiana",),
    "Iowa Hawkeyes": ("Iowa",),
    "Iowa State Cyclones": ("Iowa State",),
    "Jacksonville State Gamecocks": ("Jacksonville State",),
    "James Madison Dukes": ("James Madison",),
    "Kansas Jayhawks": ("Kansas",),
    "Kansas State Wildcats": ("Kansas State",),
    "Kennesaw State Owls": ("Kennesaw State",),
    "Kent State Golden Flashes": ("Kent State",),
    "Kentucky Wildcats": ("Kentucky",),
    "Liberty Flames": ("Liberty",),
    "Louisiana Ragin Cajuns": ("Louisiana",),
    "Louisiana Ragin' Cajuns": ("Louisiana",),
    "Louisiana Tech Bulldogs": ("Louisiana Tech",),
    "Louisville Cardinals": ("Louisville",),
    "LSU Tigers": ("LSU",),
    "Marshall Thundering Herd": ("Marshall",),
    "Maryland Terrapins": ("Maryland",),
    "Massachusetts Minutemen": ("Massachusetts", "UMass"),
    "UMass Minutemen": ("Massachusetts", "UMass"),
    "Memphis Tigers": ("Memphis",),
    "Miami Hurricanes": ("Miami", "Miami (FL)"),
    "Miami (OH) RedHawks": ("Miami (OH)",),
    "Michigan Wolverines": ("Michigan",),
    "Michigan State Spartans": ("Michigan State",),
    "Middle Tennessee Blue Raiders": ("Middle Tennessee",),
    "Minnesota Golden Gophers": ("Minnesota",),
    "Mississippi State Bulldogs": ("Mississippi State",),
    "Missouri Tigers": ("Missouri",),
    "Missouri State Bears": ("Missouri State",),
    "Navy Midshipmen": ("Navy",),
    "NC State Wolfpack": ("NC State",),
    "Nebraska Cornhuskers": ("Nebraska",),
    "Nevada Wolf Pack": ("Nevada",),
    "New Mexico Lobos": ("New Mexico",),
    "New Mexico State Aggies": ("New Mexico State",),
    "North Carolina Tar Heels": ("North Carolina",),
    "North Texas Mean Green": ("North Texas",),
    "Northern Illinois Huskies": ("Northern Illinois",),
    "Northwestern Wildcats": ("Northwestern",),
    "Notre Dame Fighting Irish": ("Notre Dame",),
    "Ohio Bobcats": ("Ohio",),
    "Ohio State Buckeyes": ("Ohio State",),
    "Oklahoma Sooners": ("Oklahoma",),
    "Oklahoma State Cowboys": ("Oklahoma State",),
    "Old Dominion Monarchs": ("Old Dominion",),
    "Ole Miss Rebels": ("Ole Miss",),
    "Oregon Ducks": ("Oregon",),
    "Oregon State Beavers": ("Oregon State",),
    "Penn State Nittany Lions": ("Penn State",),
    "Pittsburgh Panthers": ("Pittsburgh",),
    "Purdue Boilermakers": ("Purdue",),
    "Rice Owls": ("Rice",),
    "Rutgers Scarlet Knights": ("Rutgers",),
    "Sam Houston State Bearkats": ("Sam Houston", "Sam Houston State"),
    "Sam Houston Bearkats": ("Sam Houston", "Sam Houston State"),
    "San Diego State Aztecs": ("San Diego State",),
    "San Jose State Spartans": ("San José State", "San Jose State"),
    "San José State Spartans": ("San José State", "San Jose State"),
    "SMU Mustangs": ("SMU",),
    "South Alabama Jaguars": ("South Alabama",),
    "South Carolina Gamecocks": ("South Carolina",),
    "South Florida Bulls": ("South Florida",),
    "Southern Miss Golden Eagles": ("Southern Miss",),
    "Stanford Cardinal": ("Stanford",),
    "Syracuse Orange": ("Syracuse",),
    "TCU Horned Frogs": ("TCU",),
    "Temple Owls": ("Temple",),
    "Tennessee Volunteers": ("Tennessee",),
    "Texas Longhorns": ("Texas",),
    "Texas A&M Aggies": ("Texas A&M",),
    "Texas State Bobcats": ("Texas State",),
    "Texas Tech Red Raiders": ("Texas Tech",),
    "Toledo Rockets": ("Toledo",),
    "Troy Trojans": ("Troy",),
    "Tulane Green Wave": ("Tulane",),
    "Tulsa Golden Hurricane": ("Tulsa",),
    "UAB Blazers": ("UAB",),
    "UCF Knights": ("UCF",),
    "UCLA Bruins": ("UCLA",),
    "UL Monroe Warhawks": ("UL Monroe",),
    "UNLV Rebels": ("UNLV",),
    "USC Trojans": ("USC",),
    "Utah Utes": ("Utah",),
    "Utah State Aggies": ("Utah State",),
    "UTEP Miners": ("UTEP",),
    "UTSA Roadrunners": ("UTSA",),
    "Vanderbilt Commodores": ("Vanderbilt",),
    "Virginia Cavaliers": ("Virginia",),
    "Virginia Tech Hokies": ("Virginia Tech",),
    "Wake Forest Demon Deacons": ("Wake Forest",),
    "Washington Huskies": ("Washington",),
    "Washington State Cougars": ("Washington State",),
    "West Virginia Mountaineers": ("West Virginia",),
    "Western Kentucky Hilltoppers": ("Western Kentucky",),
    "Western Michigan Broncos": ("Western Michigan",),
    "Wisconsin Badgers": ("Wisconsin",),
    "Wyoming Cowboys": ("Wyoming",),
}


def seed_odds_aliases(session):
    """Add missing catalog entries in the caller's fenced refresh transaction."""
    schools = defaultdict(list)
    for alias in session.scalars(select(TeamAlias).where(
            TeamAlias.provider == "cfbd", TeamAlias.classification == "fbs")):
        schools[(alias.season, alias.source_name)].append(alias)
    existing = list(session.scalars(select(TeamAlias).where(TeamAlias.provider == "odds")))
    occupied = {(alias.season, value) for alias in existing
                for value in (alias.source_name, alias.source_identity)}
    inserted = 0
    for season in {season for season, _ in schools}:
        for source, names in ODDS_TEAMS.items():
            candidates = [alias for school in names for alias in schools.get((season, school), [])]
            if len(candidates) != 1 or (season, source) in occupied:
                continue
            session.add(TeamAlias(provider="odds", season=season, source_identity=source,
                source_name=source, canonical_team=candidates[0].canonical_team, classification="fbs"))
            occupied.add((season, source))
            inserted += 1
    session.flush()
    return inserted

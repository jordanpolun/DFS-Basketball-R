import time
import urllib.request
import pandas as pd
import datetime
import os
import unidecode

def main():

    print("Reading fantasy rosters\n")
    fantasy_rosters = getFantasyRosters()
    fantasy_rosters.to_csv("Player IDs.csv", index=False)
    #fantasy_rosters = fantasy_rosters[fantasy_rosters["Fantasy.Team"] == "Hinkie's Redux"]

    print("Getting team data from 2000-2020\n")
    team_data = getTeamData(2000, 2021)

    for index, row in fantasy_rosters.iterrows():
        id = row["ID"]
        print("Working on", id, "-", row["Fantasy.Team"])
        name, team = getBasicInfo(id)

        print("Getting game logs for", name)
        gamelogs_df = pd.DataFrame()
        urls = getGameLogURLs(id)

        # If we already have past gamelogs, just get this season's and add it to the dataframe.
        if os.path.exists("Game Logs/" + id + " Game Logs.csv"):
            
            print(id, "game logs exist. Getting current season data")
            gamelogs_df = gamelogs_df.append(pd.read_csv("Game Logs/" + id + " Game Logs.csv"), sort=False)
            current_season = getGameLogs(urls[-1], team_data)
            current_season = current_season[current_season["Date"] > gamelogs_df["Date"].iloc[-1]]
            print("\tAdded", len(current_season), "game(s)")
            gamelogs_df = gamelogs_df.append(current_season, sort=False)

        # Otherwise, get all past gamelogs
        else:
            for url in urls:
                year = url[-4:]
                print("\tGetting game logs for", year)
                try:
                    gamelogs_df = gamelogs_df.append(getGameLogs(url, team_data), ignore_index=True)
                except Exception as e:
                    print("Unable to pull game logs for", id, url)
                    print(e)
                    
        gamelogs_df.to_csv("Game Logs/" + id + " Game Logs.csv", index=False)

        print("Getting schedule for", team)
        schedule_df = getSchedule(team, team_data["2020"])
        schedule_df.to_csv("Player Schedules/" + id + " Schedule.csv", index=False)

        print()


def getFantasyRosters():
    rosters_source = open("Rosters.html", "r", encoding="utf-8").read()
    tables_source = rosters_source.split('class="Grid-u-1-2 Pend-xl')[1:]
    rows = []
    for table_source in tables_source:
        team = findBetween(table_source, '>', '<', table_source.find('/nba/'))
        rows_source = table_source.split('<td class="player last">')[1:]
        for row_source in rows_source:
            name = findBetween(row_source, '>', '<', row_source.find('Nowrap name F-link'))
            pos = findBetween(row_source, " - ", "<")
            if name.count(" ") > 1:
                name = name[:name.rfind(" ")]
            rows.append({
                "Name": name,
                "Position": pos,
                "Fantasy.Team": team
            })
    team_rosters_df = pd.DataFrame(rows)
    team_rosters_df = findBRIDs(team_rosters_df)
    return team_rosters_df


def findBRIDs(team_rosters_df):
    ids_source = getSourceCode("https://www.basketball-reference.com/leagues/NBA_2020_per_game.html")
    ids_table = findBetween(ids_source, "<tbody>", "</tbody>")
    source_rows = ids_table.split('<tr class="full_table" >')
    rows = []
    for row in source_rows:
        row_data = {
            "Name": unidecode.unidecode(findBetween(row, '.html">', '</a>').strip()),
            "ID": findBetween(row, 'data-append-csv="', '" data-stat')
        }
        rows.append(row_data)
    id_lookup = pd.DataFrame(rows)

    team_rosters_df = pd.merge(team_rosters_df, id_lookup,
                               left_on='Name',
                               right_on='Name',
                               how='inner')

    return team_rosters_df


def getGameLogURLs(id):
    source_code = getSourceCode("https://www.basketball-reference.com/players/" + id[0] + "/" + id + ".html")
    table = findBetween(source_code, '<strong>Game Logs</strong>', '</ul>')
    rows = table.split('<li>')[1:]
    urls = []
    for row in rows:
        url = findBetween(row, 'href="', '">')
        if "playoffs" not in url:
            urls.append(url)
    return urls


def getGameLogs(url, team_data):
    source_code = getSourceCode("https://www.basketball-reference.com/" + url)
    source_table = findBetween(source_code, "<tbody>", "</tbody>")
    source_rows = source_table.split("<tr id=")[1:]
    rows = []
    year = url[-4:]
    for row in source_rows:
        rows.append(parseGameRow(row, source_rows, year, team_data))
    return pd.DataFrame(rows)


def parseGameRow(row, rows, year, team_ranks):
    game = {}
    fantasy_points = 0
    for col in row.split("<td"):
        stat = findBetween(col, 'data-stat="', '"')
        if stat == "date_game":
            # Get date of game
            date = findBetween(col, '.html">', '</a>').split('-')
            date = datetime.date(int(date[0]), int(date[1]), int(date[2]))

            # Get date of game before
            row_before = rows[rows.index(row) - 1]
            col_before = findBetween(row_before, 'date_game" >', '/a>')
            date_before = findBetween(col_before, '>', '<').split('-')
            date_before = datetime.date(int(date_before[0]), int(date_before[1]), int(date_before[2]))
            days_rest = abs(date - date_before).days

            game["Date"] = pd.to_datetime(date)
            game["Month"] = date.strftime("%B")
            game["Day"] = date.strftime("%A")
            game["Rest"] = days_rest
            game["Season"] = year

        if stat == "opp_id":
            game["Opponent"] = findBetween(col, '/teams/', '/')
            year_ranks = team_ranks[year]
            for team_stat in year_ranks.columns:
                game["opp_" + team_stat] = year_ranks.loc[game["Opponent"], team_stat]

        # Get team stats
        if stat == "team_id":
            game["Team"] = findBetween(col, '/teams/', '/')
            year_ranks = team_ranks[year]
            for team_stat in year_ranks.columns:
                game["team_" + team_stat] = year_ranks.loc[game["Team"], team_stat]

        # Get if home/road
        if stat == "game_location":
            if findBetween(col, '>', '</t') == "@":
                game["Place"] = "Road"
            else:
                game["Place"] = "Home"

        # Get fantasy_points generated
        if stat in ("orb", "drb", "ast", "stl", "blk", "tov", "pf", "pts",
                    "plus_minus"):
            try:
                value = int(findBetween(col, '>', '<'))
            except:
                value = 0
            game[stat] = value
            if stat == "orb":
                fantasy_points += (value * 1.5)
            if stat in ("pts", "drb"):
                fantasy_points += value
            if stat in ("ast", "stl"):
                fantasy_points += (value * 2)
            if stat == "blk":
                fantasy_points += (value * 3)
            if stat in ("tov", "pf"):
                fantasy_points -= value

    # Add in double-doubles
    dd = sum(i >= 10 for i in [(game["orb"] + game["drb"]), game["ast"], game["pts"], game["stl"], game["blk"]])
    if dd >= 2:
        fantasy_points += 5

    # Add fantasy points column
    game["fp"] = fantasy_points
    return game


def getTeamData(start, end):
    team_data = {}
    for year in range(start, end):
        source_code = getSourceCode('https://www.basketball-reference.com/leagues/NBA_' + str(year) + '.html')
        team_per_game = parseTeamTable("Team Per Game Stats", source_code)
        opp_per_game = parseTeamTable("Opponent Per Game Stats", source_code)
        year_data = team_per_game.join(opp_per_game, on="team_name")
        team_data[str(year)] = year_data
    
    return team_data
        

def parseTeamTable(table_name, source_code):
    table = findBetween(source_code, table_name, "</tbody>")
    source_rows = table.split("<tr >")[1:]
    rows = []
    for row in source_rows:
        row_data = {}            
        cols = row.split("<td")[1:]
        for col in cols:
            stat = findBetween(col, 'data-stat="', '"')
            value = findBetween(col, '>', '<', col.find('data-stat'))
            if stat == "team_name":
                value = findBetween(row, '/teams/', '/')
            try:
                row_data[stat] = float(value)
            except:
                row_data[stat] = value
                
        rows.append(row_data)
    table_df = pd.DataFrame(rows).set_index("team_name")
    table_df = table_df.drop(["g", "mp"], axis=1)
    return table_df


def getSchedule(team, team_data):
    source_code = getSourceCode('https://www.basketball-reference.com/teams/' + team + '/2020_games.html')
    rows = source_code.split("<tr >")[1:]
    games = []
    for row in rows:
        date = getDateFromRow(row)
        games.append(parseScheduleRow(row, rows, date, team, team_data))
    return pd.DataFrame(games)


def parseScheduleRow(row, rows, date, team, team_data):
    # Get place
    place = "Home"
    if '>@<' in row:
        place = "Road"

    # Get days rest
    days_rest = getDaysRestFromRow(row, rows)

    game = {
        "Date": str(date),
        "Season": 2020,
        "Place": place,
        "Month": date.strftime('%B'),
        "Rest": days_rest,
        "Opponent": findBetween(row, '/teams/', '/2020.html'),
        "Day": date.strftime("%A")
    }

    # Get team stats
    for team_stat in team_data.columns:
        game["team_" + team_stat] = team_data.loc[team, team_stat]
        game["opp_" + team_stat] = team_data.loc[game["Opponent"], team_stat]

    return game


def getDateFromRow(row):
    date = findBetween(row, 'csk="', '"').split('-')
    date = datetime.date(int(date[0]), int(date[1]), int(date[2]))
    return date


def getDaysRestFromRow(row, rows):
    date = getDateFromRow(row)
    date_before = getDateFromRow(rows[rows.index(row) - 1])
    days_rest = abs(date - date_before).days
    return days_rest


def getBasicInfo(id):
    source_code = getSourceCode('https://www.basketball-reference.com/players/' + id[0] + '/' + id + '.html')
    name = findBetween(source_code, "<title>", " Stats")
    team = findBetween(source_code, "'/teams/", "/2020.html")[:3]
    return name, team


def getSourceCode(inputURL):
    webURL = urllib.request.urlopen(inputURL)
    data = webURL.read()
    return data.decode(webURL.headers.get_content_charset(), errors="replace")


def findBetween(string, substring_1, substring_2, after_index=0):
    start = string.find(substring_1, after_index) + len(substring_1)
    end = string.find(substring_2, start)
    return string[start: end]


if __name__ == "__main__":
    print("Starting up...")
    start = time.time()
    main()
    print("Total run time:", round(time.time() - start, 3))

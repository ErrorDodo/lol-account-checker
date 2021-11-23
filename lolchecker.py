from datetime import datetime
import requests, os, concurrent.futures, json, time, traceback

#
# Paste you accounts below separated by commas
#
ACCOUNTS = "user:pass, user1:pass1,user2:pass2"

#
# Timeout between each account check (in seconds)
# Set to 0 for no timeout (May cause temporary rate limiting)
#
TIMEOUT = 5


class Constants:
    AUTH_URL = "https://auth.riotgames.com/api/v1/authorization"
    INFO_URL = "https://auth.riotgames.com/userinfo"
    INVENTORY_URL = "https://{region_id}.cap.riotgames.com/lolinventoryservice/v2/inventories/simple?"
    DETAILED_INVENTORY_URL = "https://{region_id}.cap.riotgames.com/lolinventoryservice/v2/inventoriesWithLoyalty?"
    STORE_URL = "https://{region_tag}.store.leagueoflegends.com/storefront/v3/view/misc?language=en_US"
    HISTORY_URL = "https://{region_tag}.store.leagueoflegends.com/storefront/v3/history/purchase"
    MATCHS_URL = "https://acs.leagueoflegends.com/v1/stats/player_history/auth?begIndex=0&endIndex=1"

    # bl1tzgg rank checking endpoint
    RANK_URL = "https://riot.iesdev.com/graphql?query=query%20LeagueProfile%28%24summoner_name%3AString%2C%24summoner_id%3AString%2C%24account_id%3AString%2C%24region%3ARegion%21%2C%24puuid%3AString%29%7BleagueProfile%28summoner_name%3A%24summoner_name%2Csummoner_id%3A%24summoner_id%2Caccount_id%3A%24account_id%2Cregion%3A%24region%2Cpuuid%3A%24puuid%29%7BlatestRanks%7Bqueue%20tier%20rank%20leaguePoints%7D%7D%7D&variables=%7B%22summoner_name%22%3A%22{summoner_name}%22%2C%22region%22%3A%22{region_id}%22%7D"

    CHAMPION_DATA_URL = "https://cdn.communitydragon.org/latest/champion/"
    CHAMPION_IDS_URL = "http://ddragon.leagueoflegends.com/cdn/{game_version}/data/en_US/champion.json"
    VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"

    INVENTORY_TYPES = [
        "TOURNAMENT_TROPHY",
        "TOURNAMENT_FLAG",
        "TOURNAMENT_FRAME",
        "TOURNAMENT_LOGO",
        "GEAR",
        "SKIN_UPGRADE_RECALL",
        "SPELL_BOOK_PAGE",
        "BOOST",
        "BUNDLES",
        "CHAMPION",
        "CHAMPION_SKIN",
        "EMOTE",
        "GIFT",
        "HEXTECH_CRAFTING",
        "MYSTERY",
        "RUNE",
        "STATSTONE",
        "SUMMONER_CUSTOMIZATION",
        "SUMMONER_ICON",
        "TEAM_SKIN_PURCHASE",
        "TRANSFER",
        "COMPANION",
        "TFT_MAP_SKIN",
        "WARD_SKIN",
        "AUGMENT_SLOT",
    ]
    LOCATION_PARAMETERS = {
        "BR1": "lolriot.mia1.br1",
        "EUN1": "lolriot.euc1.eun1",
        "EUW1": "lolriot.ams1.euw1",
        "JP1": "lolriot.nrt1.jp1",
        "LA1": "lolriot.mia1.la1",
        "LA2": "lolriot.mia1.la2",
        "NA1": "lolriot.pdx2.na1",
        "OC1": "lolriot.pdx1.oc1",
        "RU": "lolriot.euc1.ru",
        "TR1": "lolriot.euc1.tr1",
    }


class ChampionData:
    def __init__(self):
        game_version = requests.get(Constants.VERSION_URL).json()
        self.game_version = game_version[0]

    def build_champion_data(self):
        champion_ids = requests.get(Constants.CHAMPION_IDS_URL.format(game_version=self.game_version)).json()
        champion_data_builder = {
            "champions": {int(value["key"]): champion_name for (champion_name, value) in champion_ids["data"].items()}
        }
        champion_data_builder["version"] = self.game_version
        champion_data_builder["skins"] = {}

        champion_urls = [
            Constants.CHAMPION_DATA_URL + str(champion_id) + "/data"
            for champion_id in champion_data_builder["champions"].keys()
        ]

        def load_url(url):
            champion_data = requests.get(url)
            return champion_data

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_url = (executor.submit(load_url, url) for url in champion_urls)
            for future in concurrent.futures.as_completed(future_to_url):
                data = future.result().json()
                for skin in data["skins"]:
                    champion_data_builder["skins"][skin["id"]] = skin["name"]
                    if "chromas" in skin:
                        for chroma in skin["chromas"]:
                            champion_data_builder["skins"][chroma["id"]] = chroma["name"] + " (Chroma)"

        return champion_data_builder

    def get_champion_data(self):
        CHAMPION_FILE_PATH = f"data{os.path.sep}champion_data.json"

        if not os.path.exists(CHAMPION_FILE_PATH):
            os.makedirs(os.path.dirname(CHAMPION_FILE_PATH))

        if not os.path.exists(CHAMPION_FILE_PATH):
            file = open(CHAMPION_FILE_PATH, "x", encoding="utf-8")
            json.dump({"version": "0"}, file, ensure_ascii=False, indent=2)
            file.close()

        updated_champion_data = {}
        champion_data = {}

        with open(CHAMPION_FILE_PATH, "r", encoding="utf-8") as reader:
            champion_data = json.load(reader)

        with open(CHAMPION_FILE_PATH, "w", encoding="utf-8") as writer:
            if champion_data["version"] != self.game_version:
                champion_data = self.build_champion_data()
                updated_champion_data = champion_data
                json.dump(champion_data, writer, ensure_ascii=False, indent=2)
            else:
                updated_champion_data = champion_data
                json.dump(champion_data, writer, ensure_ascii=False, indent=2)

        return updated_champion_data


class AccountChecker:
    def __init__(self, username, password, proxy={}):
        self.username = username
        self.password = password
        self.session = requests.Session()

        self.session.proxies.update(proxy)

        tokens = self._authorize()
        self.access_token = tokens[1]
        self.id_token = tokens[3]

        auth = {"Authorization": f"Bearer {self.access_token}"}
        self.session.headers.update(auth)

        self.user_info = self._get_user_info()
        self.region_id = self.user_info["region"]["id"]
        self.region_tag = self.user_info["region"]["tag"]
        self.summoner_name = self.user_info["lol_account"]["summoner_name"]

        self.purchase_history = self.get_purchase_history()

    def _authorize(self):
        auth_data = {
            "client_id": "riot-client",
            "nonce": "1",
            "redirect_uri": "http://localhost/redirect",
            "response_type": "token id_token",
            "scope": "openid link ban lol_region",
        }
        login_data = {
            "type": "auth",
            "username": self.username,
            "password": self.password,
        }

        self.session.post(url=Constants.AUTH_URL, json=auth_data)

        response = self.session.put(url=Constants.AUTH_URL, json=login_data).json()
        # print (response, '-=-=-')
        # uri format
        # "http://local/redirect#access_token=...
        # &scope=...&id_token=...&token_type=
        # &expires_in=...
        try:
            uri = response["response"]["parameters"]["uri"]
        except:
            print(f"Error authenticating {self.username}!")
            print(f"Response: {response}")
            raise

        tokens = [x.split("&")[0] for x in uri.split("=")]
        return tokens

    def _get_user_info(self):
        return self.session.post(url=Constants.INFO_URL).json()

    def get_inventory(self, types=Constants.INVENTORY_TYPES):
        champion_data_builder = ChampionData()
        champion_data = champion_data_builder.get_champion_data()

        query = {
            "puuid": self.user_info["sub"],
            "location": Constants.LOCATION_PARAMETERS[self.region_id],
            "accountId": self.user_info["lol"]["cuid"],
        }
        query_string = "&".join([f"{k}={v}" for k, v in query.items()] + [f"inventoryTypes={t}" for t in types])

        response = self.session.get(url=Constants.INVENTORY_URL.format(region_id=self.region_id) + query_string)

        try:
            result = response.json()["data"]["items"]
        except:
            print(f"Failed to get inventory data on {self.username}")
            print(f"Response: {response}")
            return {"CHAMPION": [], "CHAMPION_SKINS": []}

        result["CHAMPION"] = [champion_data["champions"][str(id)] for id in result["CHAMPION"]]
        result["CHAMPION_SKIN"] = [champion_data["skins"][str(id)] for id in result["CHAMPION_SKIN"]]

        return result

    def get_balance(self):
        response = self.session.get(Constants.STORE_URL.format(region_tag=self.region_tag)).json()
        return response["player"]

    def get_purchase_history(self):
        response = self.session.get(Constants.HISTORY_URL.format(region_tag=self.region_tag)).json()
        return response

    def refundable_RP(self):
        history = self.purchase_history
        refund_num = history["refundCreditsRemaining"]
        refundables = [
            x["amountSpent"] for x in history["transactions"] if x["refundable"] and x["currencyType"] == "RP"
        ]
        result = sum(sorted(refundables, reverse=True)[:refund_num])
        return result

    def refundable_IP(self):
        history = self.purchase_history
        refund_num = history["refundCreditsRemaining"]
        refundables = [
            x["amountSpent"] for x in history["transactions"] if x["refundable"] and x["currencyType"] == "IP"
        ]
        result = sum(sorted(refundables, reverse=True)[:refund_num])
        return result

    def last_play(self):
        response = self.session.get(Constants.MATCHS_URL).json()
        if len(response["games"]["games"]) != 0:
            timeCreation = response["games"]["games"][0]["gameCreation"]

            dateTime = datetime.fromtimestamp(int(timeCreation / 1000)).strftime("%Y-%m-%d %H:%M:%S")

            return dateTime
        else:
            return "No previous games"

    def get_rank(self):
        response = requests.get(
            Constants.RANK_URL.format(region_id=self.region_id, summoner_name=self.summoner_name)
        ).json()
        try:
            rank = response["data"]["leagueProfile"]["latestRanks"]
        except:
            print(f"Failed getting rank of {self.username}")
            print(f"Response: {response}")
            return "Unranked"

        if rank:
            for queue in rank:
                if queue["queue"] == "RANKED_SOLO_5X5":
                    return f'{queue["tier"]} {queue["rank"]} {queue["leaguePoints"]} LP'
        return "Unranked"

    def print_info(self):
        inventory_data = self.get_inventory()
        ip_value = self.refundable_IP()
        rp_value = self.refundable_RP()
        refunds = self.purchase_history["refundCreditsRemaining"]
        region = self.region_tag.upper()
        ban_status = f"True ({self.user_info['ban']['code']})" if self.user_info["ban"]["code"] else "False"
        name = self.summoner_name
        level = self.user_info["lol_account"]["summoner_level"]
        balance = self.get_balance()
        last_game = self.last_play()
        champions = ", ".join(inventory_data["CHAMPION"])
        champion_skins = ", ".join(inventory_data["CHAMPION_SKIN"])
        rp_curr = balance["rp"]
        ip_curr = balance["ip"]
        rank = self.get_rank()
        ret_str = [
            f" | Region: {region}",
            f"Name: {name}",
            f"Login: {self.username}:{self.password}",
            f"Last Game: {last_game}",
            f"Level: {level}",
            f"Rank: {rank}",
            f"IP: {ip_curr} - Refundable {ip_value}",
            f"RP: {rp_curr} - Refundable {rp_value}",
            f"Refunds: {refunds}",
            f"Banned: {ban_status}",
            "\n",
            "\n",
            f"Champions ({len(inventory_data['CHAMPION'])}): {champions}",
            "\n",
            "\n",
            f"Skins ({len(inventory_data['CHAMPION_SKIN'])}): {champion_skins}",
            "\n",
            "\n",
            "\n",
        ]
        return " | ".join(ret_str)


account_list = [i for i in ACCOUNTS.replace(" ", "").split(",")]


def load_account(account):
    user, pw = account.split(":")
    # account_checker = AccountChecker(user, pw, {"https": "https://PROXY:PORT"})
    account_checker = AccountChecker(user, pw)
    return account_checker


time1 = time.time()
print(f"Checking/building champion data...")
cache_champion_data = ChampionData()
cache_champion_data.get_champion_data()
time2 = time.time()
print(f"Took {time2-time1:.2f} s")

time1 = time.time()
print(f"Checking accounts, please wait...")
for account in account_list:
    if TIMEOUT > 0:
        print(f"Waiting {TIMEOUT} seconds before checking account...")
        time.sleep(TIMEOUT)
    (username, password) = account.split(":")
    try:
        # To use a proxy, may not work
        # account_checker = AccountChecker(username, password, {"https": "https://PROXY:PORT"})
        account_checker = AccountChecker(username, password)
        with open(f"accounts-{str(time1)}.txt", "a", encoding="utf-8") as account_writer:
            account_writer.write(account_checker.print_info())
    except:
        print(f"Error occured while checking {username}")
        print(traceback.format_exc())

time2 = time.time()
print(f"Complete! Account information located in accounts-{str(time1)}.txt")
print(f"Took {time2-time1:.2f} s")
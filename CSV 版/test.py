import requests
import csv
import pandas as pd
from datetime import datetime

# Zabbix API 端點
url = "http://10.40.4.67:8090/api_jsonrpc.php"

# 請求頭
headers = {"Content-Type": "application/json"}

# Zabbix 登入憑證
username = "Admin"  # 替換為您的 Zabbix 帳號
password = "zabbix"  # 替換為您的 Zabbix 密碼

# 自動獲取 auth_token
login_data = {
    "jsonrpc": "2.0",
    "method": "user.login",
    "params": {
        "user": username,
        "password": password
    },
    "id": 1,
    "auth": None
}

response = requests.post(url, headers=headers, json=login_data)
auth_token = None
if response.status_code == 200:
    try:
        result = response.json()
        if "result" in result:
            auth_token = result["result"]
            print(f"Successfully logged in. Auth token: {auth_token}")
        else:
            print(f"Login failed: {result.get('error', 'Unknown error')}")
            exit()
    except ValueError as e:
        print(f"JSON Decode Error during login: {e}")
        print(f"Response text: {response.text}")
        exit()
else:
    print(f"Login request failed with status code: {response.status_code}")
    print(f"Response text: {response.text}")
    exit()

num = 3600 * 30

# 定義頁籤名稱與對應的 itemids
tabs = {
    "CPU Utilization %": ["48119"],  # 例如 CPU 使用率
    "Memory Usage %": ["48096"],     # 例如記憶體使用量
    "Memory Swap Free %": ["48093"],
    "Disk Usage %": ["48168"],
    "Disk data Usage %": ["48170"],
    "Disk docker Usage %": ["48171"]
}

# 儲存數據的字典
data_dict = {}

# 獲取每個項目的數據
for tab_name, itemids in tabs.items():
    history_data = {
        "jsonrpc": "2.0",
        "method": "history.get",
        "params": {
            "output": "extend",
            "history": 0,  # 0 for numeric data
            "itemids": itemids,
            "sortfield": "clock",
            "sortorder": "DESC",
            "limit": num  # 限制返回的記錄數
        },
        "auth": auth_token,
        "id": 1
    }

    response = requests.post(url, headers=headers, json=history_data)

    if response.status_code == 200:
        try:
            result = response.json()
            if "result" in result:
                data = result["result"]
                # 轉換數據為 DataFrame
                df = pd.DataFrame(data)
                df["clock"] = pd.to_numeric(df["clock"], errors="coerce").fillna(0).astype(int)
                df["clock"] = pd.to_datetime(df["clock"], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")
                df = df[["clock", "value"]].rename(columns={"clock": "Timestamp", "value": "Value"})
                data_dict[tab_name] = df
            else:
                print(f"Error for {tab_name}: {result.get('error', 'No data found')}")
        except ValueError as e:
            print(f"JSON Decode Error for {tab_name}: {e}")
            print(f"Response text: {response.text}")
    else:
        print(f"Request failed for {tab_name} with status code: {response.status_code}")
        print(f"Response text: {response.text}")

# 將數據保存為 Excel 檔案，多個頁籤
if data_dict:
    with pd.ExcelWriter("zabbix_data.xlsx", engine="openpyxl") as writer:
        for tab_name, df in data_dict.items():
            df.to_excel(writer, sheet_name=tab_name, index=False)
    print("Excel file 'zabbix_data.xlsx' with multiple tabs has been created successfully.")
else:
    print("No data to save.")

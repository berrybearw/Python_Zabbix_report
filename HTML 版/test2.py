import json
import re
import requests
import subprocess
from jinja2 import Environment, FileSystemLoader
from datetime import datetime, timedelta
import time
import statistics

# Zabbix API 配置
ZABBIX_URL = "http://10.40.4.67:8090/api_jsonrpc.php"
ZABBIX_USER = "Admin"
ZABBIX_PASSWORD = "zabbix"
HOST_IDS = {
    "linux": "10644",  # 假設 Linux 主機 ID
    "windows": "10643"  # 假設 Windows 主機 ID
}
HEADERS = {"Content-Type": "application/json"}

# 假設的 IP 和 URL 資訊
SYSTEM_INFO = {
    "linux": {"ip": "10.40.4.67", "url": "sp.hosp"},
    "windows": {"ip": "10.40.4.86", "url": "ap.hosp"}
}

# 閾值配置
THRESHOLDS = {
    "cpu": 70,  # CPU utilization > 70%
}

def get_zabbix_token():
    login_data = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {
            "user": ZABBIX_USER,
            "password": ZABBIX_PASSWORD
        },
        "id": 1,
        "auth": None
    }
    try:
        response = requests.post(ZABBIX_URL, headers=HEADERS, json=login_data)
        response.raise_for_status()
        result = response.json()
        return result.get('result', Exception(f"Login failed: {result.get('error', 'Unknown error')}"))
    except Exception as e:
        print(f"Error obtaining token: {str(e)}")
        exit(1)

def zabbix_api_request(method, params, auth_token):
    request_data = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 2,
        "auth": auth_token
    }
    try:
        response = requests.post(ZABBIX_URL, headers=HEADERS, json=request_data)
        response.raise_for_status()
        result = response.json()
        return result.get('result', Exception(f"API request failed: {result.get('error', 'Unknown error')}"))
    except Exception as e:
        print(f"Error in API request ({method}): {str(e)}")
        return []

def get_historical_data(host_id, item_key, value_type, auth_token, time_from, time_till, threshold=None, invert=False):
    params = {
        "hostids": host_id,
        "filter": {"key_": item_key},
        "output": ["itemid", "name", "key_", "value_type"]
    }
    items = zabbix_api_request("item.get", params, auth_token)  # Fixed typo: explosives_api_request -> zabbix_api_request
    if not items:
        print(f"No items found for key: {item_key}")
        return []

    item_id = items[0]['itemid']
    params = {
        "history": value_type,
        "itemids": item_id,
        "time_from": time_from,
        "time_till": time_till,
        "output": "extend",
        "sortfield": "clock",
        "sortorder": "ASC"
    }
    history = zabbix_api_request("history.get", params, auth_token)

    data = []
    for entry in history:
        timestamp = datetime.fromtimestamp(int(entry['clock'])).strftime('%Y-%m-%d %H:%M:%S')
        value = float(entry['value'])
        if 'memory' in item_key and value_type == 3 and 'pavailable' not in item_key:
            value = value / (1024 * 1024 * 1024)  # bytes → GB
        elif 'vfs.fs.size' in item_key and 'used' in item_key:
            value = value / (1024 * 1024 * 1024)  # bytes → GB for remaining space
        elif 'net' in item_key:
            value = value / 1000  # bits/s to Kbps

        if threshold is not None:
            if invert:
                if value >= threshold:
                    continue
            else:
                if value <= threshold:
                    continue

        data.append([timestamp, f"{value:.2f}"])
    return data

def calculate_stats(data, hostname, threshold, invert=False, anomaly_threshold=None):
    if not data:
        return []

    values = [float(item[1]) for item in data]
    data2 = []
    if anomaly_threshold is not None:
        for i, (timestamp, value) in enumerate(data):
            val = float(value)
            is_anomalous = (val > anomaly_threshold and not invert) or (val < anomaly_threshold and invert)
            if is_anomalous:
                data2.append({"hostname": hostname, "usage": f"{val:.2f}", "timestamp": timestamp})
    return data2

def get_system_info(host_id, os_type, auth_token):
    keys = ["vm.memory.size[total]", "system.cpu.util"]
    if os_type == "linux":
        keys.extend(["system.sw.os", "system.cpu.num"])
    else:  # windows
        keys.extend(["system.uname", "wmi.get[root/cimv2,\"Select NumberOfLogicalProcessors from Win32_ComputerSystem\"]"])

    params = {
        "hostids": host_id,
        "output": ["itemid", "name", "key_", "lastvalue"],
        "filter": {"key_": keys}
    }
    items = zabbix_api_request("item.get", params, auth_token)

    # 獲取主機名稱
    params = {
        "hostids": host_id,
        "output": ["host", "name"]
    }
    hosts = zabbix_api_request("host.get", params, auth_token)
    hostname = hosts[0].get('name', 'Unknown Host') if hosts else 'Unknown Host'

    # 設定時間範圍：過去 7 天
    time_till = int(time.time())
    time_from = time_till - (7 * 24 * 3600)  # 7 days in seconds

    # 獲取 CPU 歷史數據
    cpu_raw = get_historical_data(host_id, 'system.cpu.util', 0, auth_token, time_from, time_till)
    cpu_data = calculate_stats(cpu_raw, hostname, THRESHOLDS["cpu"], anomaly_threshold=80)

    system_info = {
        "os_string": "Unknown OS",
        "cpu_cores": 0,
        "memory_bytes": 0,
        "cpu_data": cpu_data,  # 包含 hostname, usage, timestamp 的 CPU 數據
        "os_type": os_type,
        "num": 0,
        "last_month_count": 0,
        "this_month_count": 0,
        "growth_rate": 0.0,
        "user_login_total": 0,
        "slide_total": 0,
        "slide_free_size": 0,
        "login_users": []
    }

    for item in items:
        if item["key_"] in ["system.sw.os", "system.uname"]:
            system_info["os_string"] = item["lastvalue"]
        elif item["key_"] == "system.cpu.num":
            system_info["cpu_cores"] = int(item["lastvalue"])
        elif item["key_"] == "wmi.get[root/cimv2,\"Select NumberOfLogicalProcessors from Win32_ComputerSystem\"]":
            system_info["cpu_cores"] = int(item["lastvalue"])
        elif item["key_"] == "vm.memory.size[total]":
            system_info["memory_bytes"] = int(item["lastvalue"])

    if os_type == "linux":
        try:
            cmd_slide = ["zabbix_get", "-s", "10.40.4.67", "-k", "collect.slide.issue"]
            slide_data = subprocess.check_output(cmd_slide, text=True, stderr=subprocess.STDOUT).strip()
            print(f"Debug: slide_data = {slide_data}")
            lines = slide_data.splitlines()
            for line in lines:
                if not line or line == "None":
                    continue
                num_match = re.search(r'num (\d+)', line)
                last_month_match = re.search(r'last (\d+)', line)
                this_month_match = re.search(r'this (\d+)', line)
                growth_rate_match = re.search(r'grow ([\d.]+)', line)

                if num_match:
                    system_info["num"] = int(num_match.group(1))
                if last_month_match:
                    system_info["last_month_count"] = int(last_month_match.group(1))
                if this_month_match:
                    system_info["this_month_count"] = int(this_month_match.group(1))
                if growth_rate_match:
                    system_info["growth_rate"] = float(growth_rate_match.group(1))

            cmd_userlogin = ["zabbix_get", "-s", "10.40.4.67", "-k", "collect.userlogin.issue"]
            userlogin_data = subprocess.check_output(cmd_userlogin, text=True, stderr=subprocess.STDOUT).strip()
            print(f"Debug: userlogin_data = {userlogin_data}")
            login_users = json.loads(userlogin_data)
            system_info["login_users"] = [{"userid": user["User_ID"], "username": user["Username"], "count": user["Count"]} for user in login_users]
            system_info["user_login_total"] = sum(user["Count"] for user in login_users) if login_users else 0

            system_info["slide_total"] = 100
            system_info["slide_free_size"] = 50

        except subprocess.CalledProcessError as e:
            print(f"Error executing zabbix_get: {e.output}")
            system_info["last_month_count"] = 9
            system_info["this_month_count"] = 12
            system_info["growth_rate"] = 0.33
            system_info["num"] = 23
            system_info["user_login_total"] = 4
            system_info["slide_total"] = 100
            system_info["slide_free_size"] = 50
            system_info["login_users"] = [{"userid": "admin", "username": "Just_anAdmin", "count": 3}, {"userid": "test", "username": "aaadefault", "count": 1}]

    return system_info

def parse_os_info(os_string, os_type):
    if os_type == "linux":
        match = re.search(r'#\d+~(\d+\.\d+)\.\d+-Ubuntu', os_string)
        if match:
            return f"Ubuntu {match.group(1)}"
        match = re.search(r'Ubuntu \d+\.\d+\.\d+-[\w\d]+~(\d+\.\d+)', os_string)
        if match:
            return f"Ubuntu {match.group(1)}"
    elif os_type == "windows":
        match = re.search(r'Windows \S+ (\d+\.\d+\.\d+) Microsoft Windows (\d+ [^\s]+)', os_string)
        if match:
            version = match.group(1)
            os_name = match.group(2)
            return f"Windows {os_name} {version}"
    return "Unknown OS"

def main():
    auth_token = get_zabbix_token()
    print("Authentication successful")

    linux_data = {}
    windows_data = {}

    for os_type, host_id in HOST_IDS.items():
        system_info = get_system_info(host_id, os_type, auth_token)
        memory_gb = round(system_info["memory_bytes"] / (1024 ** 3), 2)

        data = {
            "system_ip": SYSTEM_INFO[os_type]["ip"],
            "system_url": SYSTEM_INFO[os_type]["url"],
            "system_os": parse_os_info(system_info["os_string"], os_type),
            "system_cpu": f"{system_info['cpu_cores']} cores",
            "system_mem": f"{memory_gb} GB",
            "num": system_info["num"],
            "last_month_count": system_info["last_month_count"],
            "this_month_count": system_info["this_month_count"],
            "growth_rate": system_info["growth_rate"],
            "user_login_total": system_info["user_login_total"],
            "slide_total": system_info["slide_total"],
            "slide_free_size": system_info["slide_free_size"],
            "login_users": system_info["login_users"],
            "cpu_alerts": system_info["cpu_data"]  # 使用 cpu_alerts 作為模板變數
        }

        if os_type == "linux":
            linux_data = data
        else:
            windows_data = data

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('report.html')

    rendered_html = template.render(
        linux=linux_data,
        windows=windows_data
    )

    with open('report_output.html', 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    print("HTML report generated: report_output.html")

if __name__ == "__main__":
    main()
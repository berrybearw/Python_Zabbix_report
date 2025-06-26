import json
import re
import requests
import subprocess
from jinja2 import Environment, FileSystemLoader

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

def get_system_info(host_id, os_type, auth_token):
    keys = ["vm.memory.size[total]"]
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

    system_info = {
        "os_string": "Unknown OS",
        "cpu_cores": 0,
        "memory_bytes": 0,
        "os_type": os_type,
        "num": 0,
        "last_month_count": 0,
        "this_month_count": 0,
        "growth_rate": 0.0,
        "user_login_total": 0,  # 新增字段
        "slide_total": 0,       # 新增字段
        "slide_free_size": 0,   # 新增字段
        "login_users": []       # 新增字段，儲存用戶登入數據
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

    # 僅對 Linux 執行 zabbix_get 命令
    if os_type == "linux":
        try:
            # 獲取 slide 數據
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

            # 獲取 userlogin 數據
            cmd_userlogin = ["zabbix_get", "-s", "10.40.4.67", "-k", "collect.userlogin.issue"]
            userlogin_data = subprocess.check_output(cmd_userlogin, text=True, stderr=subprocess.STDOUT).strip()
            print(f"Debug: userlogin_data = {userlogin_data}")
            # 解析 JSON
            login_users = json.loads(userlogin_data)
            system_info["login_users"] = [{"userid": user["User_ID"], "username": user["Username"], "count": user["Count"]} for user in login_users]
            # 計算總登入次數
            system_info["user_login_total"] = sum(user["Count"] for user in login_users) if login_users else 0

            # 假設 slide_total 和 slide_free_size 數據（待提供具體來源）
            system_info["slide_total"] = 100  # 預設值，需替換為實際數據
            system_info["slide_free_size"] = 50  # 預設值，需替換為實際數據

        except subprocess.CalledProcessError as e:
            print(f"Error executing zabbix_get: {e.output}")
            system_info["last_month_count"] = 9
            system_info["this_month_count"] = 12
            system_info["growth_rate"] = 0.33
            system_info["num"] = 23
            system_info["user_login_total"] = 4  # 預設值
            system_info["slide_total"] = 100     # 預設值
            system_info["slide_free_size"] = 50  # 預設值
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
    # 獲取 Zabbix 認證 token
    auth_token = get_zabbix_token()
    print("Authentication successful")

    # 儲存 Linux 和 Windows 的資料
    linux_data = {}
    windows_data = {}

    # 處理 Linux 和 Windows 主機
    for os_type, host_id in HOST_IDS.items():
        system_info = get_system_info(host_id, os_type, auth_token)
        memory_gb = round(system_info["memory_bytes"] / (1024 ** 3), 2)

        # 組織資料
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
            "login_users": system_info["login_users"]
        }

        if os_type == "linux":
            linux_data = data
        else:
            windows_data = data

    # 設定 Jinja2 環境，從當前目錄載入模板
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('report.html')

    # 渲染模板
    rendered_html = template.render(
        linux=linux_data,
        windows=windows_data
    )

    # 將渲染的 HTML 儲存到檔案
    with open('report_output.html', 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    print("HTML report generated: report_output.html")

if __name__ == "__main__":
    main()

import requests
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from datetime import datetime, timedelta
import time

# Zabbix API configuration
ZABBIX_URL = "http://10.40.4.67:8090/api_jsonrpc.php"
ZABBIX_USER = "Admin"
ZABBIX_PASSWORD = "zabbix"
HOST_ID = "10644"
HEADERS = {"Content-Type": "application/json"}

# 將資料轉為兩欄一排的格式
def format_two_column_table(data, title1="Timestamp", value1="Value", title2="Timestamp", value2="Value"):
    table_data = [[title1, value1, title2, value2]]
    for i in range(0, len(data), 2):
        row = []
        row.extend(data[i])
        if i + 1 < len(data):
            row.extend(data[i + 1])
        else:
            row.extend(["", ""])  # 補空
        table_data.append(row)
    return table_data

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
        if 'result' in result:
            return result['result']
        else:
            raise Exception(f"Login failed: {result.get('error', 'Unknown error')}")
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
        if 'result' in result:
            return result['result']
        else:
            raise Exception(f"API request failed: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"Error in API request ({method}): {str(e)}")
        return []

def get_system_info(host_id, auth_token):
    params = {
        "hostids": host_id,
        "selectInventory": ["os", "hardware", "location", "name"],
        "output": ["host", "name"]
    }
    hosts = zabbix_api_request("host.get", params, auth_token)
    if hosts:
        host = hosts[0]
        inventory = host.get('inventory', {})
        if isinstance(inventory, list) and inventory:
            inventory = inventory[0]
        elif not isinstance(inventory, dict):
            inventory = {}
        return {
            'Hostname': host.get('name', 'N/A'),
            'OS': inventory.get('os', 'N/A'),
            'Hardware': inventory.get('hardware', 'N/A'),
            'Location': inventory.get('location', 'N/A')
        }
    return {}

def get_historical_data(host_id, item_key, value_type, auth_token):
    params = {
        "hostids": host_id,
        "filter": {"key_": item_key},  # ✅ 用 filter 是精確比對
        "output": ["itemid", "name", "key_", "value_type"]
    }
    items = zabbix_api_request("item.get", params, auth_token)
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

        if 'memory' in item_key and value_type == 3:
            value = value / (1024 * 1024 * 1024)  # bytes → GB

        data.append([timestamp, f"{value:.2f}"])
    return data

def debug_list_keys(host_id, auth_token, keyword):
    params = {
        "hostids": host_id,
        "output": ["itemid", "name", "key_"]
    }
    items = zabbix_api_request("item.get", params, auth_token)
    for item in items:
        print(f"{item['name']} ")
        if keyword in item['key_']:
            print(f"{item['itemid']} | {item['name']} | {item['key_']}")


# 查詢所有主機的 hostid 和名稱
def list_hosts(auth_token):
    params = {
        "output": ["hostid", "host", "name"]
    }
    hosts = zabbix_api_request("host.get", params, auth_token)
    for host in hosts:
        print(f"hostid: {host['hostid']}, host: {host['host']}, name: {host['name']}")


# 取得時間範圍
num = 7 * 24 * 3600
time_till = int(time.time())
time_from = time_till - (num)  # 過去 7 天

# 取得資料與產生報表
auth_token = get_zabbix_token()
print("Authentication successful")

list_hosts(auth_token)
#debug_list_keys(HOST_ID, auth_token, "cpu.load")

system_info = get_system_info(HOST_ID, auth_token)
cpu_data = get_historical_data(HOST_ID, 'system.cpu.util', 0, auth_token)
mem_data = get_historical_data(HOST_ID, 'vm.memory.size[pavailable]', 0, auth_token)
load_average_data = get_historical_data(HOST_ID, 'system.cpu.load[all,avg1]', 0, auth_token)
disk_write_data = get_historical_data(HOST_ID, 'custom.iops[dm-0]', 0, auth_token)

# 建立 PDF
pdf_file = 'zabbix_report.pdf'
doc = SimpleDocTemplate(pdf_file, pagesize=letter)
styles = getSampleStyleSheet()
elements = []

# Page 1: 系統資訊
elements.append(Paragraph("System Information", styles['Title']))
elements.append(Spacer(1, 12))
for key, value in system_info.items():
    elements.append(Paragraph(f"<b>{key}:</b> {value}", styles['Normal']))
    elements.append(Spacer(1, 12))
elements.append(Spacer(1, 300))  # 換頁

# Page 2: 資料報表
elements.append(Paragraph("Historical Data (Last 7 Days)", styles['Title']))
elements.append(Spacer(1, 12))

# CPU
elements.append(Paragraph("CPU Utilization (%)", styles['Heading2']))
cpu_table_data = format_two_column_table(cpu_data[:num], "Timestamp", "Value (%)", "Timestamp", "Value (%)")
cpu_table = Table(cpu_table_data, colWidths=[120, 50, 120, 50])
cpu_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(cpu_table)
elements.append(Spacer(1, 12))

# Memory
elements.append(Paragraph("Memory Usage (GB)", styles['Heading2']))
mem_table_data = format_two_column_table(mem_data[:num], "Timestamp", "Value (GB)", "Timestamp", "Value (GB)")
mem_table = Table(mem_table_data, colWidths=[120, 50, 120, 50])
mem_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(mem_table)
elements.append(Spacer(1, 12))

# Disk Read
elements.append(Paragraph("Disk Read Operations (ops/s)", styles['Heading2']))
disk_read_table_data = format_two_column_table(load_average_data[:num], "Timestamp", "Value", "Timestamp", "Value")
disk_read_table = Table(disk_read_table_data, colWidths=[120, 50, 120, 50])
disk_read_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(disk_read_table)
elements.append(Spacer(1, 12))

# Disk Write
elements.append(Paragraph("Disk Write Operations (ops/s)", styles['Heading2']))
disk_write_table_data = format_two_column_table(disk_write_data[:num], "Timestamp", "Value", "Timestamp", "Value")
disk_write_table = Table(disk_write_table_data, colWidths=[120, 50, 120, 50])
disk_write_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(disk_write_table)

# 輸出 PDF
try:
    doc.build(elements)
    print(f"Report generated: {pdf_file}")
except Exception as e:
    print(f"Error generating PDF: {str(e)}")

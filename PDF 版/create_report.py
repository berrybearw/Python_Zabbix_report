import requests
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from datetime import datetime, timedelta
import time
import statistics

# Zabbix API configuration
THRESHOLDS = {
    "cpu": 70,           # CPU utilization > 70%
    "memory": 20,        # 可用記憶體百分比 < 20%（因為是 pavailable）
    "load": 5,           # Load average > 5
    "iops": 1000,        # IOPS > 1000 ops/s
    "disk_space": 80,    # Disk usage > 80%
    "net_traffic": 1000000  # Network traffic > 1MB/s
}

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
        "output": ["host", "name"]
    }
    hosts = zabbix_api_request("host.get", params, auth_token)
    if hosts:
        host = hosts[0]
        uname_result = zabbix_api_request("item.get", {
            "hostids": host_id,
            "search": {"key_": "system.uname"},
            "output": "extend",
            "sortfield": "name"
        }, auth_token)
        uname = uname_result[0]['lastvalue'] if uname_result else 'N/A'
        return {
            'Hostname': host.get('name', 'N/A'),
            'OS': uname,
            'Hardware': 'Linux System',
            'Location': 'N/A'
        }
    return {}

def get_historical_data(host_id, item_key, value_type, auth_token, threshold=None, invert=False):
    params = {
        "hostids": host_id,
        "filter": {"key_": item_key},
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

def calculate_stats(data, threshold, invert=False, anomaly_threshold=None):
    if not data:
        return {
            'max': 'N/A', 'avg': 'N/A', 'min': 'N/A',
            'violations': 0, 'anomaly_duration': '0s'
        }

    values = [float(item[1]) for item in data]
    max_val = max(values)
    avg_val = statistics.mean(values)
    min_val = min(values)
    
    # Count threshold violations
    violations = sum(1 for val in values if (val > threshold and not invert) or (val < threshold and invert))
    
    # Calculate anomaly duration (consecutive periods above/below anomaly_threshold)
    anomaly_duration = 0
    in_anomaly = False
    anomaly_start = None
    if anomaly_threshold is not None:
        for i, (timestamp, value) in enumerate(data):
            val = float(value)
            is_anomalous = (val > anomaly_threshold and not invert) or (val < anomaly_threshold and invert)
            
            if is_anomalous and not in_anomaly:
                in_anomaly = True
                anomaly_start = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            elif not is_anomalous and in_anomaly:
                in_anomaly = False
                anomaly_end = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                anomaly_duration += (anomaly_end - anomaly_start).total_seconds()
            elif is_anomalous and i == len(data) - 1 and in_anomaly:
                anomaly_end = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                anomaly_duration += (anomaly_end - anomaly_start).total_seconds()

    return {
        'max': f"{max_val:.2f}",
        'avg': f"{avg_val:.2f}",
        'min': f"{min_val:.2f}",
        'violations': violations,
        'anomaly_duration': f"{int(anomaly_duration)}s"
    }

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

system_info = get_system_info(HOST_ID, auth_token)
cpu_data = get_historical_data(HOST_ID, 'system.cpu.util', 0, auth_token, threshold=THRESHOLDS["cpu"])
mem_data = get_historical_data(HOST_ID, 'vm.memory.size[pavailable]', 0, auth_token, threshold=THRESHOLDS["memory"], invert=True)
load_average_data = get_historical_data(HOST_ID, 'system.cpu.load[all,avg1]', 0, auth_token, threshold=THRESHOLDS["load"])
disk_write_data = get_historical_data(HOST_ID, 'custom.iops[dm-0]', 0, auth_token, threshold=THRESHOLDS["iops"])
disk_space_data = get_historical_data(HOST_ID, 'vfs.fs.size[/,used]', 0, auth_token, threshold=THRESHOLDS["disk_space"])
net_in_data = get_historical_data(HOST_ID, 'net.if.in["ens160"]', 3, auth_token, threshold=THRESHOLDS["net_traffic"])
net_out_data = get_historical_data(HOST_ID, 'net.if.out["ens160"]', 3, auth_token, threshold=THRESHOLDS["net_traffic"])

# === 原始資料（未過濾） ===
cpu_raw = get_historical_data(HOST_ID, 'system.cpu.util', 0, auth_token)
mem_raw = get_historical_data(HOST_ID, 'vm.memory.size[pavailable]', 0, auth_token)
load_raw = get_historical_data(HOST_ID, 'system.cpu.load[all,avg1]', 0, auth_token)
iops_raw = get_historical_data(HOST_ID, 'custom.iops[dm-0]', 0, auth_token)
disk_space_raw = get_historical_data(HOST_ID, 'vfs.fs.size[/,pused]', 0, auth_token)
net_in_raw = get_historical_data(HOST_ID, 'net.if.in["ens160"]', 3, auth_token)
net_out_raw = get_historical_data(HOST_ID, 'net.if.out["ens160"]', 3, auth_token)

# 計算統計數據
cpu_stats = calculate_stats(cpu_raw, THRESHOLDS["cpu"], anomaly_threshold=80)
mem_stats = calculate_stats(mem_raw, THRESHOLDS["memory"], invert=True, anomaly_threshold=20)
load_stats = calculate_stats(load_raw, THRESHOLDS["load"], anomaly_threshold=5)
iops_stats = calculate_stats(iops_raw, THRESHOLDS["iops"], anomaly_threshold=1000)
disk_space_stats = calculate_stats(disk_space_raw, THRESHOLDS["disk_space"], anomaly_threshold=90)
net_in_stats = calculate_stats(net_in_raw, THRESHOLDS["net_traffic"], anomaly_threshold=2000000)
net_out_stats = calculate_stats(net_out_raw, THRESHOLDS["net_traffic"], anomaly_threshold=2000000)

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

# 摘要統計
elements.append(Paragraph("Summary Statistics (Last 7 Days)", styles['Title']))
elements.append(Spacer(1, 12))

stats_data = [
    ["Metric", "Max", "Average", "Min", "Thresh. Viol.", "Anomaly Dur."],
    ["CPU Utilization (%)", cpu_stats['max'], cpu_stats['avg'], cpu_stats['min'], cpu_stats['violations'], cpu_stats['anomaly_duration']],
    ["Memory Available (%)", mem_stats['max'], mem_stats['avg'], mem_stats['min'], mem_stats['violations'], mem_stats['anomaly_duration']],
    ["Load Average", load_stats['max'], load_stats['avg'], load_stats['min'], load_stats['violations'], load_stats['anomaly_duration']],
    ["Disk IOPS", iops_stats['max'], iops_stats['avg'], iops_stats['min'], iops_stats['violations'], iops_stats['anomaly_duration']],
    ["Disk Space Used (GB)", disk_space_stats['max'], disk_space_stats['avg'], disk_space_stats['min'], disk_space_stats['violations'], disk_space_stats['anomaly_duration']],
    ["Network In (Kbps)", net_in_stats['max'], net_in_stats['avg'], net_in_stats['min'], net_in_stats['violations'], net_in_stats['anomaly_duration']],
    ["Network Out (Kbps)", net_out_stats['max'], net_out_stats['avg'], net_out_stats['min'], net_out_stats['violations'], net_out_stats['anomaly_duration']]
]
stats_table = Table(stats_data, colWidths=[100, 60, 60, 60, 90, 90])
stats_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
]))
elements.append(stats_table)
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
elements.append(Paragraph("Memory Available (%)", styles['Heading2']))
mem_table_data = format_two_column_table(mem_data[:num], "Timestamp", "Value (%)", "Timestamp", "Value (%)")
mem_table = Table(mem_table_data, colWidths=[120, 50, 120, 50])
mem_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(mem_table)
elements.append(Spacer(1, 12))

# Load Average
elements.append(Paragraph("Load Average", styles['Heading2']))
load_table_data = format_two_column_table(load_average_data[:num], "Timestamp", "Value", "Timestamp", "Value")
load_table = Table(load_table_data, colWidths=[120, 50, 120, 50])
load_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(load_table)
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
elements.append(Spacer(1, 12))

# Disk Space
elements.append(Paragraph("Disk Space Used (GB)", styles['Heading2']))
disk_space_table_data = format_two_column_table(disk_space_data[:num], "Timestamp", "Value (GB)", "Timestamp", "Value (GB)")
disk_space_table = Table(disk_space_table_data, colWidths=[120, 50, 120, 50])
disk_space_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(disk_space_table)
elements.append(Spacer(1, 12))

# Network In
elements.append(Paragraph("Network In (Kbps)", styles['Heading2']))
net_in_table_data = format_two_column_table(net_in_data[:num], "Timestamp", "Value (Kbps)", "Timestamp", "Value (Kbps)")
net_in_table = Table(net_in_table_data, colWidths=[120, 50, 120, 50])
net_in_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(net_in_table)
elements.append(Spacer(1, 12))

# Network Out
elements.append(Paragraph("Network Out (Kbps)", styles['Heading2']))
net_out_table_data = format_two_column_table(net_out_data[:num], "Timestamp", "Value (Kbps)", "Timestamp", "Value (Kbps)")
net_out_table = Table(net_out_table_data, colWidths=[120, 50, 120, 50])
net_out_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(net_out_table)

# 建立第二份 PDF（含全部歷史資料）
pdf_file_raw = 'zabbix_raw_report.pdf'
doc_raw = SimpleDocTemplate(pdf_file_raw, pagesize=letter)
elements_raw = []

elements_raw.append(Paragraph("Historical Raw Data (Last 7 Days)", styles['Title']))
elements_raw.append(Spacer(1, 12))

def add_raw_section(title, data):
    elements_raw.append(Paragraph(title, styles['Heading2']))
    table_data = format_two_column_table(data[:100], "Timestamp", "Value", "Timestamp", "Value")
    table = Table(table_data, colWidths=[120, 50, 120, 50])
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black)
    ]))
    elements_raw.append(table)
    elements_raw.append(Spacer(1, 12))

add_raw_section("CPU Utilization (Raw)", cpu_raw)
add_raw_section("Memory Available (%) (Raw)", mem_raw)
add_raw_section("Load Average (Raw)", load_raw)
add_raw_section("Disk IOPS (Raw)", iops_raw)
add_raw_section("Disk Space Used (GB) (Raw)", disk_space_raw)
add_raw_section("Network In (Kbps) (Raw)", net_in_raw)
add_raw_section("Network Out (Kbps) (Raw)", net_out_raw)

try:
    doc_raw.build(elements_raw)
    print(f"Raw report generated: {pdf_file_raw}")
except Exception as e:
    print(f"Error generating raw PDF: {str(e)}")

# 輸出 PDF
try:
    doc.build(elements)
    print(f"Report generated: {pdf_file}")
except Exception as e:
    print(f"Error generating PDF: {str(e)}")

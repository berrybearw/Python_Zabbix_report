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
HOST_ID = "10643"  # Replace with your host ID
HEADERS = {"Content-Type": "application/json"}

# Function to get Zabbix API token
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

# Function to make Zabbix API request
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

# Function to get system information
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
        
        # ✅ 修正點：處理 inventory 是 list 的情況
        if isinstance(inventory, list) and inventory:
            inventory = inventory[0]
        elif not isinstance(inventory, dict):
            inventory = {}  # fallback 防呆

        return {
            'Hostname': host.get('name', 'N/A'),
            'OS': inventory.get('os', 'N/A'),
            'Hardware': inventory.get('hardware', 'N/A'),
            'Location': inventory.get('location', 'N/A')
        }
    return {}

# Function to get historical data
def get_historical_data(host_id, item_key, value_type, auth_token):
    # Get item ID
    params = {
        "hostids": host_id,
        "search": {"key_": item_key},
        "output": ["itemid", "name", "key_", "value_type"]
    }
    items = zabbix_api_request("item.get", params, auth_token)
    if not items:
        print(f"No items found for key: {item_key}")
        return []
    
    item_id = items[0]['itemid']
    # Get history data
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
        #value = float(entry['value'])
        #data.append([timestamp, f"{value:.2f}"])
        value = float(entry['value'])

        if 'memory' in item_key and value_type == 3:
            # 如果是 memory 且是 unsigned int，轉換為 MB
            value = value / (1024 * 1024 * 1024)
        
        data.append([timestamp, f"{value:.2f}"])
    return data

# 查詢所有主機的 hostid 和名稱
def list_hosts(auth_token):
    params = {
        "output": ["hostid", "host", "name"]
    }
    hosts = zabbix_api_request("host.get", params, auth_token)
    for host in hosts:
        print(f"hostid: {host['hostid']}, host: {host['host']}, name: {host['name']}")

def list_all_items(host_id, auth_token):
    params = {
        "hostids": host_id,
        "output": ["itemid", "name", "key_"]
    }
    items = zabbix_api_request("item.get", params, auth_token)
    for item in items:
        print(f"{item['itemid']} | {item['name']} | {item['key_']}")

# Get auth token
auth_token = get_zabbix_token()
print("Authentication successful")

# List all hosts
list_hosts(auth_token)

#list_all_items(HOST_ID, auth_token)

# Define time range (last 7 days)
time_till = int(time.time())
time_from = time_till - (7 * 24 * 3600)  # 7 days ago

# Collect data
system_info = get_system_info(HOST_ID, auth_token)
cpu_data = get_historical_data(HOST_ID, 'system.cpu.util', 0, auth_token)  # Float type
mem_data = get_historical_data(HOST_ID, 'vm.memory.size[used]', 3, auth_token)   # Unsigned integer
disk_read_data = get_historical_data(HOST_ID, 'vfs.dev.read[sda,ops]', 0, auth_token)  # Float type
disk_write_data = get_historical_data(HOST_ID, 'vfs.dev.write[sda,ops]', 0, auth_token)  # Float type

# Create PDF report
pdf_file = 'zabbix_report.pdf'
doc = SimpleDocTemplate(pdf_file, pagesize=letter)
styles = getSampleStyleSheet()
elements = []

# Page 1: System Information
elements.append(Paragraph("System Information", styles['Title']))
elements.append(Spacer(1, 12))
for key, value in system_info.items():
    elements.append(Paragraph(f"<b>{key}:</b> {value}", styles['Normal']))
    elements.append(Spacer(1, 12))

# Force new page
elements.append(Spacer(1, 300))  # Large spacer to push to next page

# Page 2: Historical Data
elements.append(Paragraph("Historical Data (Last 7 Days)", styles['Title']))
elements.append(Spacer(1, 12))

# CPU Utilization Table
elements.append(Paragraph("CPU Utilization (%)", styles['Heading2']))
cpu_table_data = [['Timestamp', 'Value (%)']] + cpu_data[:30]  # Limit to 10 entries
cpu_table = Table(cpu_table_data)
cpu_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(cpu_table)
elements.append(Spacer(1, 12))

# Memory Usage Table
elements.append(Paragraph("Memory Usage (GB)", styles['Heading2']))
mem_table_data = [['Timestamp', 'Value (GB)']] + mem_data[:30]
mem_table = Table(mem_table_data)
mem_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(mem_table)
elements.append(Spacer(1, 12))

# Disk I/O Tables
elements.append(Paragraph("Disk Read Operations (ops/s)", styles['Heading2']))
disk_read_table_data = [['Timestamp', 'Value (ops/s)']] + disk_read_data[:10]
disk_read_table = Table(disk_read_table_data)
disk_read_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(disk_read_table)
elements.append(Spacer(1, 12))

elements.append(Paragraph("Disk Write Operations (ops/s)", styles['Heading2']))
disk_write_table_data = [['Timestamp', 'Value (ops/s)']] + disk_write_data[:10]
disk_write_table = Table(disk_write_table_data)
disk_write_table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
   ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
]))
elements.append(disk_write_table)

# Build PDF
try:
    doc.build(elements)
    print(f"Report generated: {pdf_file}")
except Exception as e:
    print(f"Error generating PDF: {str(e)}")

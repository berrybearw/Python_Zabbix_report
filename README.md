## 執行方式
- 搭配 Zabbix API
- 讀取到 token 之後呼叫各指標
- python3 create_report.py

## 執行結果

```text
Authentication successful
hostid: 10643, host: DESKTOP-O975H1S, name: Windows
hostid: 10644, host: 10.40.4.67, name: 10.40.4.67
hostid: 10084, host: Zabbix server, name: Zabbix server
Raw report generated: zabbix_raw_report.pdf
Report generated: zabbix_report.pdf
```

產生 pdf

一般資訊 + 數據超標紀錄
- zabbix_report.pdf

歷史數據
- zabbix_raw_report.pdf

## 執行方式
- 搭配 Zabbix API
- agent 是部署在 Linux, Windows
- 讀取到 token 之後呼叫各指標
- report.html 與 test2.py 放同一個目錄
- zabbix_conf 內的 scripts 放入 /etc/zabbix/scripts
- 參照 zabbix_conf zabbix_agentd.conf 補上相關指令設定
- 重啟 agent
- 給予 zabbix 能執行 docker，把 zabbix 加入 docker 群組(sudo usermod -aG docker zabbix)
- python3 test2.py

## 說明
- zabbix_conf 是 zabbix 執行指令的設定檔
- zabbix_conf/scripts/a.sh : 撈取 Cytomine 玻片 (總量,前一個月量,本月量,成長率)
- zabbix_conf/scripts/user_login_num.sh : 撈取 Cytomine 本月登入用戶總量與前十名

## 套用模板
- 模板 : html
- 連結數據 : Jinja2
- 數據 : python + json

製作一個樣式 html，可以透過 bootstrap 美化

然後把內容替換成 Jinja2 語法

就可用 json 等，把資料帶入

- 範例
  - 多筆數據自動產生
```html
{% for item in linux.cpu_alerts %}
<tr>
  <td>{{ loop.index }}</td>
  <td>{{ item.hostname }}</td>
  <td>{{ item.usage }}</td>
  <td>{{ item.timestamp }}</td>
</tr>
{% endfor %}
```

## 執行結果

- 產生一個 html
- report_output.html

如圖

![image](https://github.com/user-attachments/assets/2d94a550-d346-4a53-a19f-e644be5591d8)




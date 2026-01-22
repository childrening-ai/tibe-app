import requests
from bs4 import BeautifulSoup

# 設定目標：抓取其中一頁就好
url = "https://www.tibe.org.tw/tw/calendar/69" 

response = requests.get(url)
response.encoding = 'utf-8'
soup = BeautifulSoup(response.text, 'html.parser')

# 找到第一個標題
title = soup.find(class_="header-text")

if title:
    print(f"✅ 成功找到標題：{title.text.strip()}")
    print("-" * 30)
    
    # 測試 1：看爸爸 (Parent)
    parent = title.parent
    print(f"📦 【父層 (Parent) 的 class】：{parent.get('class')}")
    # 檢查爸爸裡面有沒有 'info-name'
    if parent.find(class_="info-name"):
        print("   👉 爸爸裡面有 'info-name' (時間地點)！")
    else:
        print("   ❌ 爸爸裡面找不到 'info-name'。 (範圍太小)")

    print("-" * 30)

    # 測試 2：看爺爺 (Grandparent)
    grandparent = parent.parent
    print(f"📦 【爺爺 (Grandparent) 的 class】：{grandparent.get('class')}")
    # 檢查爺爺裡面有沒有 'info-name'
    if grandparent.find(class_="info-name"):
        print("   👉 爺爺裡面有 'info-name' (時間地點)！")
    else:
        print("   ❌ 爺爺裡面也找不到。")

    print("-" * 30)
    
    # 印出爺爺的前 500 個字 HTML 讓我幫您分析
    print("👇 請把下面這段 HTML 貼給我：")
    print(grandparent.prettify()[:1000])

else:
    print("❌ 連標題都找不到，可能是網站結構變了。")
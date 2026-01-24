import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 設定檔路徑
CREDS_FILE = "secrets.json"

def empty_bot_trash():
    print("🧹 準備強制清空機器人垃圾桶...")

    try:
        # 1. 讀取 JSON 並處理 Streamlit 格式
        with open(CREDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if "gcp_service_account" in data:
            info = data["gcp_service_account"]
        else:
            info = data

        # 2. 建立 Drive API 連線
        creds = service_account.Credentials.from_service_account_info(info)
        service = build('drive', 'v3', credentials=creds)
        
        # 3. 查詢空間現況 (清空前)
        about = service.about().get(fields="storageQuota").execute()
        usage_before = int(about['storageQuota'].get('usage', 0)) / (1024**3)
        print(f"📉 清空前佔用空間: {usage_before:.2f} GB")

        # 4. 執行清空垃圾桶指令
        print("🔥 正在執行 emptyTrash()...")
        try:
            service.files().emptyTrash().execute()
            print("✅ 垃圾桶已清空！")
        except Exception as e:
            print(f"⚠️ 清空垃圾桶時發生狀況 (可能已經是空的): {e}")

        # 5. 查詢空間現況 (清空後)
        about = service.about().get(fields="storageQuota").execute()
        usage_after = int(about['storageQuota'].get('usage', 0)) / (1024**3)
        print(f"📉 清空後佔用空間: {usage_after:.2f} GB")
        
        if usage_after == 0:
            print("🎉 恭喜！空間已歸零，請現在去執行 app.py！")
        else:
            print("🤔 還有殘留檔案？那可能是非 Google Sheet 的檔案 (如圖片/PDF)。")

    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

if __name__ == "__main__":
    empty_bot_trash()
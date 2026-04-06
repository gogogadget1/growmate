import asyncio
import os
from tapo import ApiClient
from dotenv import load_dotenv

# Load env for credentials
load_dotenv()

async def main():
    email = os.getenv("TAPO_EMAIL")
    password = os.getenv("TAPO_PASSWORD")
    hub_ip = "192.168.178.69"
    
    print(f"Connecting to Tapo Hub at {hub_ip}...")
    try:
        client = ApiClient(email, password)
        hub = await client.h100(hub_ip)
        
        print("Fetching child devices...")
        child_devices = await hub.get_child_device_list()
        
        print("-" * 50)
        print(f"{'Nickname':<20} | {'Model':<10} | {'Device ID'}")
        print("-" * 50)
        
        for child in child_devices:
            info = child.to_dict()
            nickname = info.get("nickname", "Unknown")
            model = info.get("model", "Unknown")
            device_id = child.device_id
            print(f"{nickname:<20} | {model:<10} | {device_id}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from kasa import SmartBulb

IP = "192.168.1.3"   # IP of your TP-Link Kasa light

async def set_brightness(level: int):
    """
    Set brightness of the TP-Link bulb.
    :param level: Brightness percentage (1–100)
    """
    bulb = SmartBulb(IP)
    await bulb.update()
    
    if not bulb.is_on:
        print("Bulb is OFF, turning it ON...")
        await bulb.turn_on()

    print(f"Setting brightness to {level}%")
    await bulb.set_brightness(level)
    await bulb.update()
    print("Done. Current brightness:", bulb.brightness)

if __name__ == "__main__":
    try:
        level = int(input("Enter brightness level (1-100): "))
        if 1 <= level <= 100:
            asyncio.run(set_brightness(level))
        else:
            print("Invalid input! Please enter a value between 1 and 100.")
    except ValueError:
        print("Please enter a number between 1 and 100.")
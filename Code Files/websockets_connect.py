import asyncio
import websocket
import numpy as np
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# WebSocket URL
WS_URL = "wss://677c562b-0436-440b-9454-1e39a4bd51d8-00-tkficnqryakd.pike.replit.dev/ws"

# Audio parameters (match ESP32)
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit PCM
SAMPLES_PER_CHUNK = 256  # ~16ms
CHUNK_INTERVAL = 0.016  # 16ms in seconds

async def send_audio():
    ws = None
    while True:
        try:
            # Initialize WebSocket
            ws = websocket.WebSocket()
            ws.connect(WS_URL, header={"User-Agent": "Python-WebSocket/1.0"})
            logger.info(f"Connected to {WS_URL}")

            while True:
                # Generate simulated audio (16-bit PCM, random like INMP441)
                audio_chunk = np.random.randint(-32768, 32767, SAMPLES_PER_CHUNK, dtype=np.int16)
                audio_bytes = audio_chunk.tobytes()

                # Send binary data
                start_time = time.time()
                ws.send(audio_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
                elapsed = (time.time() - start_time) * 1000
                logger.info(f"Sent {len(audio_bytes)} bytes, Time: {elapsed:.2f}ms")

                # Wait to match audio rate (~16ms)
                await asyncio.sleep(CHUNK_INTERVAL)

        except websocket.WebSocketException as e:
            logger.error(f"WebSocket error: {e}")
            if ws:
                ws.close()
            logger.info("Reconnecting in 2 seconds...")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            if ws:
                ws.close()
            logger.info("Reconnecting in 2 seconds...")
            await asyncio.sleep(2)

async def main():
    try:
        await send_audio()
    except KeyboardInterrupt:
        logger.info("Stopped by user")

if __name__ == "__main__":
    asyncio.run(main())
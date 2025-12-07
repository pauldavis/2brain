#!/usr/bin/env python3
import logging
import sys
import time

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from app.services.vectorizer import backfill_loop

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


def main():
    if load_dotenv:
        load_dotenv()

    logger.info("Starting manual vector backfill...")
    start_time = time.time()

    try:
        count = backfill_loop(batch_size=50)
        elapsed = time.time() - start_time
        logger.info(
            f"Backfill complete. Processed {count} segments in {elapsed:.2f} seconds."
        )
    except KeyboardInterrupt:
        logger.warning("Backfill interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

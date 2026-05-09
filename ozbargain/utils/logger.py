import logging
import os
import sys
from pythonjsonlogger import jsonlogger

def setup_logger(name: str = "ozbargain"):
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if already setup
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # 1. Stdout Handler (Human Readable)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_formatter = logging.Formatter(
        '[%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    stdout_handler.setFormatter(stdout_formatter)
    logger.addHandler(stdout_handler)
    
    # 2. File Handler (JSON)
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    log_file = os.path.join(log_dir, "monitor.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    
    # JSON Formatter
    json_formatter = jsonlogger.JsonFormatter(
        '%(timestamp)s %(levelname)s %(name)s %(message)s',
        timestamp=True
    )
    file_handler.setFormatter(json_formatter)
    logger.addHandler(file_handler)
    
    # 3. Logtail Handler (Optional)
    logtail_token = os.getenv("LOGTAIL_TOKEN")
    if logtail_token:
        try:
            from logtail import LogtailHandler
            logtail_handler = LogtailHandler(source_token=logtail_token)
            logtail_handler.setLevel(logging.INFO)
            logger.addHandler(logtail_handler)
            logger.info("Logtail handler initialized.")
        except ImportError:
            logger.warning("logtail-python not installed, skipping LogtailHandler.")
        except Exception as e:
            logger.error(f"Failed to initialize LogtailHandler: {e}")
            
    return logger

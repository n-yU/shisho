from logging import getLogger, StreamHandler, DEBUG, Formatter
from typing import Dict, Any
import yaml
from pathlib import Path

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(message)s'))


def get_config() -> Dict[str, Any]:
    """司書設定ファイル（yml形式）読み込み
    Returns:
        Dict[str, Any]: 司書設定
    """
    config_path = Path('./config/config.yml')

    try:
        with open(config_path) as f:
            conf = yaml.safe_load(f)
    except Exception as e:
        logger.error('コンフィグの読み込みに失敗しました')
        logger.error('フォーマットに問題がある可能性があります')
        logger.error(e)
        exit()

    return conf

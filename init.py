from logging import getLogger, StreamHandler, DEBUG, Formatter
import json
import elasticsearch

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(message)s'))


def confirm() -> bool:
    """書籍データリセット確認

    Returns:
        bool: リセット許可 -> True
    """
    while 1:
        choice = input('[tosho42] 書籍データをリセットします．本当によろしいですか？[yes/N]: ')
        if choice == 'yes':
            return True
        elif choice.lower() in {'n', 'no'}:
            return False


if __name__ == '__main__':
    if confirm():
        es = elasticsearch.Elasticsearch('elasticsearch')
        try:
            es.indices.delete(index='book')  # bookインデックスの全ドキュメント全削除
            logger.debug('書籍データをリセットしました')
        except elasticsearch.exceptions.NotFoundError:
            logger.debug('初回セットアップのため書籍データはリセットされません')

        # Elasticsearchマッピング読み込み（テーブル定義）
        with open('./elasticsearch/body.json', mode='r', encoding='utf-8') as f:
            body = json.load(f)

        es.indices.create(index='book', body=body)  # bookインデックス新規作成
        es.close()
        logger.debug('書籍データを初期化しました')
    else:
        logger.debug('書籍データのリセットをキャンセルしました')

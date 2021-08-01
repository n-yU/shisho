from logging import getLogger, StreamHandler, DEBUG, Formatter
from typing import Dict, Union
import sys
from pathlib import Path
import random
import string
from datetime import datetime as dt
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.sql.functions import current_timestamp
from sqlalchemy import Column, String, Integer, create_engine, TIMESTAMP, text, ForeignKey
from flask_login import UserMixin
from flask_bcrypt import Bcrypt

parent_dir = str(Path(__file__).parent.parent.resolve())
sys.path.append(parent_dir)
from config import get_config

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(message)s'))

DATABASE = 'mysql://{0}:{1}@{2}/{3}?charset=utf8mb4'.format(
    'test', 'test', 'mysql:3306', 'app')    # TODO: 環境変数から参照

ENGINE = create_engine(DATABASE, convert_unicode=True, echo=True)   # DBエンジン作成
session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=ENGINE))  # scoped_sessionによるセッション生成

Base = declarative_base()   # モデルベースクラス

# scoped_sessionではテーブル定義の継承元クラスにqueryプロパティを仕込む
# ref.) https://qiita.com/tosizo/items/86d3c60a4bb70eb1656e#scoped_session%E3%81%AB%E3%82%88%E3%82%8B%E7%94%9F%E6%88%90orm%E7%B7%A8
Base.query = session.query_property()


class User(Base):
    """ユーザテーブル
    """
    __tablename__ = 'users'  # テーブル名
    uId = Column('uId', String(100), primary_key=True, nullable=False)  # ユーザID
    sId = Column('sId', String(200), nullable=False)                    # セッションID
    name = Column('name', String(200), nullable=False)                  # ユーザ名
    password = Column('password', String(100), nullable=False)             # パスワード
    created_at = Column('created_at', TIMESTAMP, server_default=current_timestamp())    # 作成日
    updated_at = Column('updated_at', TIMESTAMP, nullable=False,                        # 更新日
                        server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))

    histories = relationship('History', backref='users')    # Historyとのリレーション


class History(Base):
    """閲覧履歴テーブル
    """
    __tablename__ = 'histories'  # テーブル名
    id = Column(Integer, primary_key=True)                      # ログID
    uId = Column('uId', String(100), ForeignKey('users.uId'))   # ユーザID（ユーザテーブルとの外部キー）
    sId = Column('sId', String(200), nullable=False)            # セッションID
    bId = Column('bId', String(200), nullable=False)                # 書籍ID
    ts = Column('ts', TIMESTAMP, nullable=False, server_default=current_timestamp())    # タイムスタンプ


class LoginUser(UserMixin, User):
    """ログイン機能用ユーザモデル
    """

    def get_id(self) -> str:
        """認証用ユーザID取得

        Returns:
            str:ユーザID
        """
        return self.uId


def get_sId(n=12) -> str:
    """セッションID生成

    Args:
        n (int, optional): 文字列サイズ. Defaults to 12.

    Returns:
        str: セッションID
    """
    # ref.) https://qiita.com/Scstechr/items/c3b2eb291f7c5b81902a
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def record_history(user: LoginUser, bId: str) -> None:
    """書籍閲覧履歴記録

    Args:
        user (LoginUser): ユーザ
        bId (str): 閲覧書籍ISBN-10
    """

    # 履歴記録
    log = History(uId=user.uId, sId=user.sId, bId=bId)
    session.add(log)
    session.commit()

    # DEBUG:
    # for user in session.query(User).join(History, User.uId == History.uId).all():
    #     for log in user.histories:
    #         logger.debug('{0}:{1} -> {2} ({3})'.format(log.uId, log.sId, log.bId, log.ts))


def get_user_history(user: LoginUser) -> Dict[int, Dict[int, Union[int, str, dt]]]:
    """書籍閲覧履歴取得

    Args:
        user (LoginUser): ユーザ

    Returns:
        Dict[int, Dict[int, Union[int, str, dt]]]: 閲覧履歴
    """

    raw_user_history = History.query.filter(History.uId == user.uId).all()

    # 変換: History -> Dict(key:lId)
    user_history = dict()
    for log in raw_user_history:
        user_history[log.id] = dict()
        user_history[log.id]['uId'] = log.uId
        user_history[log.id]['sId'] = log.sId
        user_history[log.id]['bId'] = log.bId
        user_history[log.id]['ts'] = log.ts

    return user_history


def main():
    """全テーブル初期化
    """
    config = get_config()   # 司書設定
    Base.metadata.drop_all(bind=ENGINE)     # 全テーブル削除
    Base.metadata.create_all(bind=ENGINE)   # 全テーブル作成

    # 管理者アカウント作成
    admin_user = LoginUser(uId=config['admin_user_id'], sId=get_sId(), name=config['admin_user_name'],
                           password=Bcrypt().generate_password_hash(config['admin_user_password']).decode('utf-8'))
    session.add(admin_user)    # INSERT: 管理者アカウント
    session.commit()        # テーブル更新


if __name__ == "__main__":
    main()

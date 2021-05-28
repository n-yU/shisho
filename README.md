# shisho
**(2021.05.28現在) 開発中のため正常な動作は保証していません．使用はご遠慮ください．**

![ライセンス](https://img.shields.io/github/license/n-yU/shisho)
![コードサイズ](https://img.shields.io/github/languages/code-size/n-yU/shisho)

- 司書(shisho)のように書籍の貸出や案内を行うWebアプリです．
- [自身が所属する研究室](http://www.ds.lab.uec.ac.jp/)が抱える数百冊の書籍を効率的に管理したいと思ったのが製作のきっかけです．
- ログイン必須としており，会社・研究室などクローズドな環境を想定しています（ユーザ認証機能は現在実装中）．
- 書籍の検索には全文検索エンジンのElasticsearchを使用しています．
- Webアプリ構築にはflaskを使っています．
- Doc2Vec(Paragraph2Vec[Le+, 2014])を活用した非パーソナライズ推薦機能が実装されてます．
- 提案システム[梛木+, 2020]を活用したパーソナライズ推薦機能を実装予定です．
    - ただし，書籍（アイテム）の分散表現構築にはItem2Vec[Barkan+, 2016]ではなくDoc2Vecを使用しています．

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**

- [📷 イメージ](#-%E3%82%A4%E3%83%A1%E3%83%BC%E3%82%B8)
  - [トップページ](#%E3%83%88%E3%83%83%E3%83%97%E3%83%9A%E3%83%BC%E3%82%B8)
  - [書籍個別ページ](#%E6%9B%B8%E7%B1%8D%E5%80%8B%E5%88%A5%E3%83%9A%E3%83%BC%E3%82%B8)
- [🔍 環境](#-%E7%92%B0%E5%A2%83)
- [📂 ディレクトリ構成](#-%E3%83%87%E3%82%A3%E3%83%AC%E3%82%AF%E3%83%88%E3%83%AA%E6%A7%8B%E6%88%90)
- [🚀 セットアップ](#-%E3%82%BB%E3%83%83%E3%83%88%E3%82%A2%E3%83%83%E3%83%97)
- [📚 参考](#-%E5%8F%82%E8%80%83)
- [☎️ お問い合わせ](#-%E3%81%8A%E5%95%8F%E3%81%84%E5%90%88%E3%82%8F%E3%81%9B)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->


## 📷 イメージ
画像は開発中のものです．

### トップページ
<img src="https://user-images.githubusercontent.com/51310314/119985816-1c295000-bffe-11eb-996b-5bea1e0b9566.png" width="800px">

### 書籍個別ページ
<img src="https://user-images.githubusercontent.com/51310314/119985827-1e8baa00-bffe-11eb-8f25-2aba8562c830.png" width="800px">


## 🔍 環境
- Python 3.8.8
    - [requirements.txt](./backend/requirements.txt)
- Elasticsearch 7.8.0
- MeCab 0.996


## 📂 ディレクトリ構成
```
.
├── backend         # バックエンド
│   ├── Dockerfile          # python3コンテナ
│   ├── doc2vecwrapper.py   # Doc2Vecラッパークラス
│   ├── openbd.py           # openBDクラス
│   └── requirements.txt    # 必須Pythonライブラリ
├── config          # 設定
│   └── config.yml          # 設定ファイル
├── elasticsearch   # Elasticsearch（全文検索エンジン）
│   ├── body.json
│   └── Dockerfile          # elasticsearchコンテナ
├── static          # 静的ファイル
│   ├── css
│   │   └── my-sheet.css    # カスタムCSS
│   ├── img                 # 固定画像
│   │   ├── book.png        # デフォルト表紙
│   │   └── favicon.ico     # ファビコン
│   └── js
│       └── my-script.js    # カスタムスクリプト
├── templates       # HTML
│   ├── book.html           # 書籍個別
│   ├── delete.html         # 削除問い合わせ
│   ├── deleted.html        # 削除完了
│   ├── explore.html        # 詳細検索
│   ├── index.html          # トップページ
│   ├── layout.html         # 基本レイアウト
│   ├── register.html       # 登録問い合わせ
│   ├── registered.html     # 登録完了  
│   ├── search.html         # 検索
│   └── shelf.html          # 本棚（書籍一覧）
├── app.py
├── docker-compose.yml
├── init.py                 # elasticsearchインデックス初期化
├── references.md           # 参考サイト
└── register.py             # 書籍一括登録
```


## 🚀 セットアップ
2回目からは1,2の実行は不要です

1. **`config/book.txt`に登録したい書籍のISBN-10を1冊につき1行記述**

2. **以下コマンドを順に実行**
    ```bash
    docker-compose up
    python init.py
    python register.py
    ```

3. **サーバ起動**
    ```
    flask run
    ```
    `ctrl+C`でサーバーを落とすことができます
4. **ブラウザから http://127.0.0.1:5000/ へアクセスできることを確認**


## 📚 参考
- 参考サイト: [references.md](./references.md) にまとめています
- 文献
    - [Le+, 2014]: Q. Le, T. Mikolov: Distributed Representations of Sentences and Documents, Proc. of the 31st Int. Conf. on Machine Learning, pp.1188–1196,2014.
    - [梛木+, 2020] 梛木 佑真, 岡本 一志: アイテム分散表現の階層化・集約演算に基づくセッションベース推薦システム, Webインテリジェンスとインタラクション研究会 第16回研究会予稿集, 56-59, 2020.
    - [Barkan+, 2016]: O. Barkan, N. Koenigstein: Item2Vec: Neural Item Embedding for Collaborative Filtering, In 2016 IEEE 26th Int. Workshop on Machine Learning for Signal Processing (MLSP), pp.1–6, 2016.


## ☎️ お問い合わせ
- 本リポジトリについて質問等ありましたら，[Twitter](https://twitter.com/nyu923)へのリプライが最も反応が早いです（DMはご遠慮ください）．
- 必要に応じてイシューを立てて頂いても結構です（現在は初期開発段階ですのでご遠慮ください）．

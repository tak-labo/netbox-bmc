# netbox-secrets 連携ガイド

`netbox_bmc` は BMC の認証情報(username/password)を [netbox-secrets](https://github.com/Onemind-Services-LLC/netbox-secrets)
経由で管理できる。本書は導入手順と、実際に動作確認した手順を記す。

netbox-secrets が未インストール、またはデバイスに `bmc-credentials` ロールの Secret が
見つからない場合は `BMCEndpoint.username` / `password`(平文フィールド)に自動的に
フォールバックする。詳細な実装は `netbox_bmc/credentials.py` を参照。

## 前提: プラグインのインストール

`netbox-docker` 環境の場合、`Dockerfile-Plugins` に `netbox-secrets` の pip インストールが
含まれている必要がある(`netbox_bmc` / `netbox_pdu_control` のようなローカル editable
インストールとは別に、PyPI パッケージとして追加する)。

```dockerfile
RUN uv pip install --python /opt/netbox/venv/bin/python3 \
    -e /opt/netbox-plugins/netbox-pdu-control \
    -e /opt/netbox-plugins/netbox-bmc \
    -e /opt/netbox-plugins/netbox-thermal-view \
    netbox-secrets
```

`configuration/plugins.py` の `PLUGINS` に `netbox_secrets` を追加し、イメージを再ビルドする。
`PLUGINS` に追加しただけでパッケージ自体がインストールされていないと、NetBox 起動時に
`ImproperlyConfigured: Unable to import plugin netbox_secrets: Module not found` で
コンテナが落ちるので注意。

## 1. 管理者による初回セットアップ

**Secret Role の作成**: `Secrets` → `Secret Roles` → `Add` で、slug を
`bmc-credentials` にしたロールを作成する。`netbox_bmc/credentials.py` の
`SECRET_ROLE_SLUG` がこの値を固定で参照するため、slug は変更不可。

## 2. 各ユーザーの鍵登録(初回のみ、ユーザーごと)

netbox-secrets は公開鍵暗号方式(RSA)で「master_key」を保護する設計になっている。

1. RSA 鍵ペアを生成する(2048bit 以上)。手元の端末で生成し、秘密鍵はサーバーに送らない。
   - NetBox 側にも `GET /api/plugins/secrets/generate-rsa-keypair/` という鍵ペア生成
     エンドポイントがあるが、生成された秘密鍵はレスポンスで一度返るだけで保存されないため、
     本番運用では信頼できる自分の環境で生成する方が安全。
2. `Secrets` → `User Keys` → 自分の User Key 編集画面で公開鍵(PEM)を登録して保存する。
   - このとき、まだ誰もアクティブな User Key を持っていない場合は、サーバー側で
     ランダムな `master_key` が自動生成され、あなたの公開鍵で暗号化されて保存される
     (`UserKey.save()` の自動 activate ロジック)。これがシステム全体で共有される唯一の
     master_key になる。
   - 2人目以降のユーザーは、既にアクティブな管理者に `ActivateUserkeyView`
     (`Secrets` → `User Keys` → 対象ユーザー → `Activate`)経由で自分の公開鍵に対して
     同じ master_key を暗号化してもらう必要がある(自分の秘密鍵だけでは新規登録できない)。

## 3. Device への Secret 割り当て

対象 Device の Secrets タブから `Add Secret` する。

| フィールド | 値 |
|---|---|
| Role | `bmc-credentials` |
| Name | BMC のユーザー名(平文フィールド) |
| Plaintext | BMC のパスワード(RSA 暗号化されて保存) |

netbox_bmc 側の `BMCEndpoint.username` / `password`(平文フォールバック)は空欄のままでよい。

## 4. UI 操作時のセッションアンロック

Build Modules・電源操作など、`endpoint.get_driver(request=request)` を呼ぶ操作
(`BuildModulesView` / `PowerActionView` / `IdentifyActionView` / `PowerStatusView` /
`FetchRawView` / `ConnectivityTestView`)を実行するとき、暗号化された Secret を復号する
必要がある。netbox-secrets の Secret 詳細画面を開くと秘密鍵入力モーダルが表示され、
入力すると `POST /api/plugins/secrets/session-key/` にリクエストが飛び、
`netbox_secrets_sessionid` という Cookie がセットされる。これ以降はこの Cookie が
自動的に送信されるため、ブラウザセッション中(`LOGIN_TIMEOUT` 設定に依存)は
再入力不要になる。

netbox_bmc 側は `netbox_bmc/credentials.py` の `_master_key_from_request()` が
`netbox_secrets.utils.get_session_key(request)` で Cookie / `X-Session-Key` ヘッダ /
POST の `session_key` からセッションキーを取り出し、
`SessionKey.objects.get(userkey__user=request.user).get_master_key(session_key)`
で `master_key` を復号する。

## 5. バックグラウンドジョブ用のサービスアカウント

`NetworkSyncJob` / `SensorsSyncJob` / `EventLogSyncJob` / `ManagerHealthSyncJob` などの
`request` を持たないバックグラウンドジョブは、Cookie/セッションを使えないため、専用の
サービスアカウントで復号する。

### 5.1 NetBox ユーザーの作成と権限

1. NetBox に新規ユーザーを作成する(例: `bmc-sync`)。ログイン用途ではないので強力な
   ランダムパスワードを設定し、`is_superuser` は付けない。Permission (ObjectPermission)
   で以下のように最小権限を付与する:
   - **定常運用時(推奨)**: `netbox_secrets.secret` / `secretrole` / `userkey` に対する
     **`view`** のみ。`credentials.py` の `_master_key_from_service_account()` は
     `UserKey.objects.get(user__username=...)` を生の model マネージャで直接呼ぶため、
     このジョブ経路自体は ObjectPermission の有無に左右されない。ただしこのアカウントで
     NetBox UI/APIから Secrets を閲覧・管理させたい場合はこの権限が必要になる。
   - **User Key の新規作成時のみ一時的に**: `netbox_secrets.userkey` への **`add`** も
     必要(`view` だけでは Secrets → User Keys → Add でオブジェクトを作成できない)。
     作成完了後は `view` のみに戻してよい。
   - **鍵ローテーション時のみ一時的に**: 既存 User Key の `public_key` を更新する場合は
     `add` ではなく **`change`** が必要。これも作業後は `view` のみに戻す。

   **設定例(Admin → Permissions → Add、URL: `/users/permissions/add/`)**:

   | 項目 | 値 |
   |---|---|
   | Name | `secret-access`(用途が分かる名前ならなんでも良い) |
   | Object types | `netbox_secrets \| Secret` / `netbox_secrets \| Secret Role` / `netbox_secrets \| User Key` の3つ(`Session Key` は含めない) |
   | Actions | `View` のみ(User Key 作成直後は一時的に `Add` を追加 → 作成後に外す) |
   | Users | `bmc-sync` |
   | Groups | (空のまま) |
   | Constraints | (空のまま、全インスタンス対象) |

### 5.2 RSA 鍵ペアの生成と User Key の activate

2. このユーザーで(または管理権限を持つユーザーが代理で)RSA 鍵ペアを生成する。
3. **Secrets → User Keys → Add** で `bmc-sync` ユーザーの User Key を作成する
   (この操作には上記の一時的な `add` 権限が必要)。
   - 手順2(§2)で最初の User Key が既に存在する場合、この新しい User Key は
     非アクティブな状態で作成される。
   - **Secrets → User Keys → Activate User Keys** を開き、既にアクティブな鍵を持つ
     管理者が自分の秘密鍵を使って `bmc-sync` の User Key を有効化する(master_key が
     `bmc-sync` の公開鍵でも暗号化され、`bmc-sync` の秘密鍵でも復号可能になる)。
4. `bmc-sync` の**秘密鍵**を NetBox サーバー上の安全な場所に配置する。

#### 通常環境(非Docker)

```bash
chmod 600 /opt/netbox/bmc-sync.pem
chown netbox:netbox /opt/netbox/bmc-sync.pem
```

`configuration.py` に追記:

```python
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "service_account": "bmc-sync",
        "service_private_key_path": "/opt/netbox/bmc-sync.pem",
    },
}
```

NetBox を再起動して `PLUGINS_CONFIG` を反映する。

#### Docker 環境(netbox-docker)

秘密鍵はコンテナ内のファイルシステムに存在しないため、**ホスト側から bind mount する**
必要がある(イメージに焼き込まない — 秘密鍵をビルドコンテキストやリポジトリに含めないこと)。

1. ホスト側に鍵の置き場所を用意し、パーミッションを絞る(リポジトリの外、`.gitignore`
   対象にする):

```bash
mkdir -p ../netbox-docker/secrets
mv bmc-sync.pem ../netbox-docker/secrets/
chmod 640 ../netbox-docker/secrets/bmc-sync.pem
```

**パーミッションについて:** netbox-docker の `netbox`/`netbox-worker` コンテナは
`uid=999`(`netbox` ユーザー)・`gid=0`(`root` グループ)で動作する。ファイル所有者を
`root:root` のままにする場合、`600`(所有者のみ読み取り可)ではコンテナ内の `netbox`
ユーザーが読み取れず `Permission denied` になる。**`640`**(所有者rw・グループr)にして、
グループ経由で読み取れるようにすること。

2. `docker-compose.override.yml` の `netbox`(と、定期実行させる場合は `netbox-worker`)
   サービスに volume を追加してコンテナ内へ読み取り専用でマウントする:

```yaml
services:
  netbox:
    volumes:
      - ./secrets/bmc-sync.pem:/opt/netbox/bmc-sync.pem:ro,z
  netbox-worker:
    volumes:
      - ./secrets/bmc-sync.pem:/opt/netbox/bmc-sync.pem:ro,z
```

3. `configuration/plugins.py` に追記(コンテナ内から見えるパスを指定):

```python
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "service_account": "bmc-sync",
        "service_private_key_path": "/opt/netbox/bmc-sync.pem",
    },
}
```

4. コンテナを再作成してマウント・設定を反映する:

```bash
docker compose up -d --force-recreate netbox netbox-worker
```

5. マウントできているか確認する:

```bash
docker compose exec netbox cat /opt/netbox/bmc-sync.pem | head -1
# -----BEGIN PRIVATE KEY----- 等が表示されればOK
```

### 5.3 復号の仕組み

これで `netbox_bmc/credentials.py:_master_key_from_service_account()` が
`UserKey.objects.get(user__username=service_account)` を取得し、
`UserKey.get_master_key(private_key=<pemファイルの内容>)` で `master_key` を復号する。

サービスアカウント(`bmc-sync`)まわりの認可は、独立した2つの層で構成される。**どちらか
一方だけでは不十分**で、両方が揃って初めてバックグラウンドジョブが Secret を復号できる。

- **① Unix ファイルパーミッション(ホスト〜コンテナ)**: ホスト側 `bmc-sync.pem`
  (owner=root:root, mode=640)を `:ro` で bind mount し、コンテナ内 `netbox` プロセス
  (uid=999, gid=0(root))がグループ経由で読み取る。欠けるとコンテナが秘密鍵ファイルを
  読めず `_master_key_from_service_account()` が例外を投げ、ログに ERROR が記録された上で
  平文フィールドへフォールバックする。
- **② NetBox ObjectPermission(アプリ内DB)**: `bmc-sync` ユーザーに付与された
  `view`(必要時のみ `add`/`change`)の Secret/SecretRole/UserKey 権限。
  `_master_key_from_service_account()` 自体は生の model マネージャで `UserKey` を
  取得するため直接は参照されないが、`bmc-sync` アカウント自体で NetBox UI/API から
  Secrets を閲覧・管理する場合はこちらが必要になる(§5.1 の権限テーブルを参照)。

### 5.4 動作確認

- **Web UI からの操作**(Sync ボタン、Power ON/OFF など): ログイン中のユーザー自身の
  セッションキーで復号される。ブラウザでログインしていれば追加操作は不要。
- **バックグラウンド/定期実行**(`NetworkSyncJob` 等の各 `Scheduled*SyncJob`):
  本節で設定したサービスアカウントの秘密鍵で復号される。

うまく復号できない場合(鍵の不一致、Secret が存在しない等)は `netbox_bmc.credentials`
ロガーに `ERROR` レベルで理由が記録され、既存の平文フィールドに自動フォールバックする
(処理自体は止まらない)。ログを確認する:

```bash
docker compose logs netbox-worker | grep netbox_bmc.credentials
```

### 5.5 トラブルシューティング

| 症状 | 原因の候補 |
|---|---|
| 常に平文フィールドが使われる(Secretが反映されない) | SecretRole の slug が `bmc-credentials` になっていない / Secret が対象 Device に紐づいていない |
| Web UI操作時にフォールバックする | 自分の User Key が未作成・非アクティブ、またはセッションキー期限切れ |
| バックグラウンドジョブ実行時にフォールバックする | `service_account` / `service_private_key_path` が未設定、またはそのユーザーの User Key が非アクティブ |
| エラーログに "No UserKey for service account" | `bmc-sync` の User Key が作成・activate されていない |
| エラーログに "No netbox-secrets session key found in request" | ブラウザ側でセッションキーが未取得(netbox-secrets 側のUI操作を一度行う) |
| `docker compose exec netbox cat <pem>` で `Permission denied`(Docker環境) | 秘密鍵ファイルのパーミッションが `600` かつ所有者が `root` のまま。コンテナ内の `netbox` ユーザーは `uid=999`/`gid=0(root)` で動作するため、`chmod 640` でグループ読み取りを許可する必要がある |

## 過去に見つかった不具合 (fixed)

`_master_key_from_request()` は当初、以下の2点が実際の netbox-secrets 実装と
食い違っており、常に復号に失敗して平文フィールドへ無言でフォールバックしていた
(`get_credential()` の広い `except Exception` が握りつぶすため、ログを見ないと
気付けない):

1. Cookie 名を `session_key` としていたが、正しくは `netbox_secrets_sessionid`
   (`netbox_secrets/constants.py` の `SESSION_COOKIE_NAME`)。
2. `UserKey.get_master_key(session_key)` を呼んでいたが、`UserKey.get_master_key()`
   は RSA 秘密鍵専用のメソッド(内部で `RSA.importKey(private_key)` を呼ぶ)。
   セッションキー(対称鍵)での復号は別モデルの
   `SessionKey.objects.get(userkey__user=request.user).get_master_key(session_key)`
   を使う必要がある。

修正は PR #57 で `SessionKey` モデル経由に書き換え済み。

## 動作検証手順 (このドキュメントの根拠)

以下の手順で実際に netbox-secrets 本体のコードを読み、`manage.py shell` 上で
一連のフローを実機相当で再現して検証した。

```python
from Crypto.PublicKey import RSA
from django.test import Client
from netbox_secrets.models import UserKey, SecretRole, Secret
from netbox_bmc.credentials import get_credential
import json

# 1. RSA鍵ペア生成 + UserKey登録(自動activate)
key = RSA.generate(2048)
priv_pem = key.export_key('PEM').decode()
pub_pem = key.publickey().export_key('PEM').decode()
uk = UserKey(user=some_user, public_key=pub_pem)
uk.save()
master_key = uk.get_master_key(priv_pem)

# 2. SecretRole + Secret 作成(Deviceに割り当て)
role, _ = SecretRole.objects.get_or_create(slug='bmc-credentials', defaults={'name': 'BMC Credentials'})
secret = Secret(assigned_object=device, role=role, name='someuser', plaintext='somepass')
secret.encrypt(master_key)
secret.save()

# 3. 実際のセッションキーAPIを叩いてCookieをセット(UIと同じ経路)
c = Client()
c.force_login(some_user)
c.post('/api/plugins/secrets/session-key/',
       data=json.dumps({'private_key': priv_pem}), content_type='application/json')

# 4. Cookie付きのrequestでget_credential()を呼び、正しく復号されることを確認
request = c.get('/plugins/bmc/endpoints/').wsgi_request
cred = get_credential(endpoint, request=request)
assert cred.source == "netbox_secrets"
assert cred.username == "someuser" and cred.password == "somepass"
```

バックグラウンドジョブ経路(`request=None`)も、サービスアカウント用ユーザーに対して
同様に `UserKey` を作成・activate し、`PLUGINS_CONFIG` を設定した状態で
`netbox_bmc.jobs._sync_manager_health(endpoint)` 等を直接呼び、
`source == "netbox_secrets"` で復号されることを確認済み。

いずれのテストも、検証後は作成した `Secret` / `SessionKey` / `UserKey` /
`SecretRole` / サービスアカウントユーザーを削除して後始末している。

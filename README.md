# LeRobot Hardware Plugins

HuggingFace LeRobot フレームワーク用のハードウェアプラグインコレクションです。
様々なロボットやテレオペレーションデバイスを LeRobot のインターフェースで使用することを目的としています。

## 🎯 プロジェクト概要

このリポジトリは、LeRobot エコシステムを様々なハードウェアに拡張するための **プラグイン集** です。
LeRobot の標準規約に完全準拠し、新しいハードウェアを簡単に追加/テスト可能な設計を目指しています。

## ✨ 特徴

- 🔌 **LeRobot完全準拠**: 公式の命名規約とインターフェースに準拠
- 🏗️ **モジュラー設計**: デバイス毎に独立したパッケージ構造
- 🚀 **プラグアンドプレイ**: インストールするだけで自動認識
- 📦 **依存関係分離**: デバイス固有の依存関係を明確に管理
- 🔄 **拡張性**: 新しいハードウェアを容易に追加可能
- 📊 **統合データ収集**: 全デバイス共通のデータセット作成機能


## 🖥️ 確認環境

このプロジェクトは以下の環境で開発・テストしています

### 動作確認済み環境
| OS | Python | uv | LeRobot | 状況 |
|-------|--------|-----|---------|------|
| **macOS 26.1 | 3.11.14 | 0.9.9 | v0.4.1 | ✅ |


### 必須要件
- **Python**: 3.11以上、3.12未満
- **LeRobot**: v0.4.1以上
- **パッケージマネージャー**: [uv](https://docs.astral.sh/uv/getting-started/installation/)

### ハードウェア要件
- Bluetoothアダプタ（toio用）
- USBポート（ゲームコントローラー用）
- Webカメラ（データ収集時、オプション）

## 🚀 クイックスタート

toio Core Cube を使って動作の確認が可能です

### 1. セットアップ
```bash
# リポジトリをクローン
git clone https://github.com/njima/lerobot-hardware-plugins.git
cd lerobot-hardware-plugins

# 依存関係をインストール
uv sync
```

### 2. ハードウェア準備
1. **toio Core Cube**: 電源を入れる
    - MacOSの場合、事前にペアリングはできません。テレオペレーション実行時に接続可能なtoioに接続します。(複数toioへの対応は別途スコープ)
2. **ゲームコントローラー**: USBまたはBluetoothでPCに接続

### 3. 実行
```bash
# toioのテレオペレーション実行
uv run lerobot-teleoperate \
    --robot.type=toio_follower \
    --teleop.type=toio_leader \
    --fps=60
```

🎮 ゲームコントローラーでtoioを操作可能となります！  
やったぜ！
- **左スティック**: 旋回（左右）
- **右スティック**: 前後移動



## 🤖 サポートハードウェア

### 現在サポート中
| デバイス | タイプ | 登録名 |
|---------|--------|---------|
| Sony toio Core Cube | Robot | `toio_follower` |
| ゲームコントローラー | Teleoperator | `toio_leader` |

## 🚀 インストール

```bash
git clone https://github.com/njima/lerobot-hardware-plugins.git
cd lerobot-hardware-plugins
uv sync
```

**注意**: 各プラグインの依存関係は自動的にインストールします。

## 📖 使用方法

### テレオペレーション

```bash
# 基本的なテレオペレーション
uv run lerobot-teleoperate \
    --robot.type=<robot_type> \
    --teleop.type=<teleop_type> \
    --fps=60
```

### データセット収集

```bash
# 模倣学習用データセット作成
uv run lerobot-record \
    --robot.type=<robot_type> \
    --teleop.type=<teleop_type> \
    --fps=30 \
    --dataset-name="my_dataset" \
    --num-episodes=50
```

## 📁 プロジェクト構造

```
lerobot-hardware-plugins/
├── 📄 README.md                         # プロジェクト概要（このファイル）
├── 📁 docs/                             # デバイス別ドキュメント
├── 📁 lerobot_robots/                   # ロボットプラグイン群
│   └── 📁 toio/                         # toio ロボット実装
├── 📁 lerobot_teleoperators/            # テレオペレーター群  
│   └── 📁 toio/                         # toio テレオペ実装
└── 📄 pyproject.toml                    # メイン統合設定
```

## 🛠️ 新しいプラグインの開発

- 今後追加予定

## 🐛 トラブルシューティング

### 一般的な問題

```bash
# インストール関連の問題
uv sync  # 依存関係の再同期

```

## 🤝 コントリビューション

新しいハードウェアサポートを追加したい場合：

1. **Issue 作成**: 追加したいハードウェアについて議論
2. **Fork & Clone**: このリポジトリをフォーク  
3. **プラグイン実装**: 上記の開発ガイドに従って実装
4. **テスト追加**: 単体テストとインテグレーションテストを作成
5. **ドキュメント作成**: セットアップガイドを `docs/` に追加
6. **Pull Request**: 変更内容を詳しく説明

### 貢献ガイドライン

- LeRobot の公式規約に準拠すること
- 適切なエラーハンドリングを実装すること  
- デバイス固有の依存関係を明確に分離すること
- 包括的なドキュメントを提供すること

## 📄 ライセンス

Apache License 2.0

## 🔗 関連リンク

- [🤗 HuggingFace LeRobot](https://github.com/huggingface/lerobot) - メインフレームワーク
- [📚 LeRobot Hardware Integration Guide](https://huggingface.co/docs/lerobot/integrate_hardware) - 公式統合ガイド
- [🎲 toio 公式サイト](https://toio.io/) - Sony toio 情報

---

**新しいハードウェアサポートや改善提案は [Issues](https://github.com/njima/lerobot-hardware-plugins/issues) または [Pull Requests](https://github.com/njima/lerobot-hardware-plugins/pulls) でお知らせください！** 🚀
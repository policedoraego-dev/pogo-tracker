-- ポケモンGO イベントトラッカー: Supabase テーブル設定
-- Supabase ダッシュボードの「SQL Editor」にこのファイルの内容を貼り付けて実行

-- カスタムイベントテーブル
CREATE TABLE IF NOT EXISTS custom_events (
  id          TEXT        PRIMARY KEY,
  title       TEXT        NOT NULL,
  type        TEXT        DEFAULT 'default',
  start_time  TIMESTAMPTZ,
  end_time    TIMESTAMPTZ,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 全デバイスから読み書きできるようにする（個人利用向け）
ALTER TABLE custom_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "誰でも読み取り可" ON custom_events
  FOR SELECT USING (true);

CREATE POLICY "誰でも追加可" ON custom_events
  FOR INSERT WITH CHECK (true);

CREATE POLICY "誰でも削除可" ON custom_events
  FOR DELETE USING (true);

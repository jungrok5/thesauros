"use client";

/**
 * Client component for /chart-vision — file picker + result render.
 *
 * Drag-and-drop OR click-to-select. Once a file is chosen, immediately
 * POST to /api/chart-vision/analyze and stream the result into view.
 * No state persisted across reloads (MVP).
 */
import { useEffect, useState } from "react";
import { Upload, Loader2, AlertCircle } from "lucide-react";

type AnalysisResult = {
  verdict?: string;
  trend?: { weekly?: string; monthly?: string };
  patterns?: string[];
  volume_signal?: string;
  ma_state?: string;
  ma240_position?: string;
  action_ask?: string;
  warnings?: string[];
  confidence?: number;
  raw?: string;   // fallback when model output isn't JSON-parseable
};

export function ChartVisionClient() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  // Blob URL cleanup (회고 #34) — preview 가 바뀔 때 / 컴포넌트 unmount
  // 시 이전 createObjectURL 의 메모리 해제. 모바일 safari 의 memory
  // pressure 회피.
  useEffect(() => {
    if (!preview) return;
    return () => {
      try { URL.revokeObjectURL(preview); } catch { /* ignored */ }
    };
  }, [preview]);

  async function analyze(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    setPreview(URL.createObjectURL(file));
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("/api/chart-vision/analyze", {
        method: "POST",
        body: fd,
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        setError(data.error ?? `HTTP ${r.status}`);
        return;
      }
      setResult(data.result as AnalysisResult);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) void analyze(f);
  }

  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) void analyze(f);
  }

  return (
    <div className="space-y-4">
      <label
        htmlFor="chart-file"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border bg-card hover:bg-muted/30 transition-colors p-8 cursor-pointer text-center"
      >
        {busy ? (
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        ) : (
          <Upload className="h-8 w-8 text-muted-foreground" />
        )}
        <div className="text-sm font-medium">
          {busy ? "분석 중…" : "차트 이미지 업로드"}
        </div>
        <div className="text-xs text-muted-foreground">
          {busy ? "Claude Vision 분석 (보통 5-15초)" : "클릭 또는 드래그 — PNG / JPEG / WebP / GIF, 10MB 이하"}
        </div>
        <input
          id="chart-file"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={onPick}
          disabled={busy}
          className="sr-only"
        />
      </label>

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-3 text-sm text-rose-700 dark:text-rose-300 flex items-start gap-2">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">분석 실패</div>
            <div className="text-xs mt-0.5">{error}</div>
          </div>
        </div>
      )}

      {preview && (
        <div className="rounded-lg border border-border p-3 bg-card">
          <div className="text-xs text-muted-foreground mb-2">업로드한 차트</div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={preview}
            alt="차트"
            className="max-h-[400px] mx-auto rounded-md border border-border"
          />
        </div>
      )}

      {result && <ResultCard r={result} />}
    </div>
  );
}

function ResultCard({ r }: { r: AnalysisResult }) {
  // Raw fallback — model didn't return JSON. Show the raw text so the
  // user isn't blocked.
  if (r.raw) {
    return (
      <section className="rounded-xl border-2 border-amber-500/30 bg-amber-500/5 p-4 space-y-2">
        <div className="text-xs uppercase tracking-widest text-amber-700 dark:text-amber-300">
          ⚠️ 구조화 분석 실패 — raw 결과만 표시
        </div>
        <pre className="text-xs whitespace-pre-wrap text-muted-foreground">
          {r.raw}
        </pre>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      {/* 한 줄 평 + 행동 */}
      {(r.verdict || r.action_ask) && (
        <div className="rounded-xl border-2 border-emerald-500/40 bg-emerald-500/5 p-4 space-y-2">
          {r.verdict && (
            <div className="text-sm font-semibold">📊 {r.verdict}</div>
          )}
          {r.action_ask && (
            <div className="text-xs text-muted-foreground leading-relaxed">
              💡 {r.action_ask}
            </div>
          )}
          {typeof r.confidence === "number" && (
            <div className="text-[10px] text-muted-foreground">
              신뢰도 {(r.confidence * 100).toFixed(0)}%
            </div>
          )}
        </div>
      )}

      {/* 추세 + 이평선 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
        {(r.trend?.weekly || r.trend?.monthly) && (
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="font-medium mb-1">📈 추세</div>
            {r.trend?.monthly && (
              <div className="text-muted-foreground">월봉: {r.trend.monthly}</div>
            )}
            {r.trend?.weekly && (
              <div className="text-muted-foreground">주봉: {r.trend.weekly}</div>
            )}
          </div>
        )}
        {(r.ma_state || r.ma240_position) && (
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="font-medium mb-1">📐 이평선</div>
            {r.ma_state && (
              <div className="text-muted-foreground">배열: {r.ma_state}</div>
            )}
            {r.ma240_position && (
              <div className="text-muted-foreground">240MA: {r.ma240_position}</div>
            )}
          </div>
        )}
        {r.volume_signal && (
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="font-medium mb-1">💸 거래량</div>
            <div className="text-muted-foreground">{r.volume_signal}</div>
          </div>
        )}
      </div>

      {/* 패턴 */}
      {r.patterns && r.patterns.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-3">
          <div className="text-xs font-medium mb-1">🎯 식별된 패턴</div>
          <ul className="text-xs text-muted-foreground space-y-0.5">
            {r.patterns.map((p, i) => (
              <li key={i}>· {p}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 주의점 */}
      {r.warnings && r.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
          <div className="text-xs font-medium text-amber-700 dark:text-amber-300 mb-1">
            ⚠️ 주의
          </div>
          <ul className="text-xs space-y-0.5">
            {r.warnings.map((w, i) => (
              <li key={i}>· {w}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

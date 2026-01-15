import { useEffect, useMemo, useRef, useState } from "react";
import {
  describeInstrument,
  estimateValue,
  InstrumentDescription,
  StreamEvent,
  ValuationResult,
  streamDescribe,
  streamEstimate,
} from "./api";

const emptyDescription: InstrumentDescription = {
  category: "",
  brand: "",
  model: "",
  year: null,
  condition: "",
  materials: [],
  features: [],
  notes: "",
};

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  }).format(value);

type PipelineState = "idle" | "running" | "done";
type TerminalLine = {
  text: string;
  tone?: "muted" | "accent" | "ok" | "warn";
  prefix?: string;
};

const formatFileSize = (bytes: number) => {
  if (!Number.isFinite(bytes)) {
    return "--";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return `${kb.toFixed(1)} KB`;
  }
  return `${(kb / 1024).toFixed(2)} MB`;
};

const formatPipelineStatus = (state: PipelineState) => {
  switch (state) {
    case "done":
      return "完了";
    case "running":
      return "実行中";
    default:
      return "待機";
  }
};

const clearTimers = (timersRef: { current: number[] }) => {
  timersRef.current.forEach((timerId) => window.clearTimeout(timerId));
  timersRef.current = [];
};

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState<InstrumentDescription>(
    emptyDescription,
  );
  const [valuation, setValuation] = useState<ValuationResult | null>(null);
  const [status, setStatus] = useState<"idle" | "describing" | "estimating">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [imageMeta, setImageMeta] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [visionState, setVisionState] = useState<PipelineState>("idle");
  const [visionActiveIndex, setVisionActiveIndex] = useState(-1);
  const [visionCompleted, setVisionCompleted] = useState(0);
  const [ragState, setRagState] = useState<PipelineState>("idle");
  const [ragActiveIndex, setRagActiveIndex] = useState(-1);
  const [ragCompleted, setRagCompleted] = useState(0);
  const [consoleLines, setConsoleLines] = useState<string[]>([]);
  const [streamingActive, setStreamingActive] = useState(false);
  const [streamingPhase, setStreamingPhase] = useState<"vision" | "rag" | null>(
    null,
  );
  const visionTimersRef = useRef<number[]>([]);
  const ragTimersRef = useRef<number[]>([]);
  const consoleIntervalRef = useRef<number | null>(null);
  const streamTokenRef = useRef(0);
  const describeAbortRef = useRef<AbortController | null>(null);
  const estimateAbortRef = useRef<AbortController | null>(null);
  const autoEstimateRef = useRef(false);

  const previewUrl = useMemo(
    () => (file ? URL.createObjectURL(file) : ""),
    [file],
  );

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  useEffect(() => {
    return () => {
      describeAbortRef.current?.abort();
      estimateAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!previewUrl) {
      setImageMeta(null);
      return;
    }

    const image = new Image();
    image.onload = () => {
      setImageMeta({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      setImageMeta(null);
    };
    image.src = previewUrl;

    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [previewUrl]);

  const hasDescription = useMemo(() => {
    return Boolean(
      description.category ||
        description.brand ||
        description.model ||
        description.year ||
        description.condition ||
        description.materials.length ||
        description.features.length ||
        description.notes,
    );
  }, [description]);

  const hasValuation = Boolean(valuation);

  const visionSteps = useMemo(
    () => [
      {
        title: "入力準備",
        detail: "アップロード画像を読み込み",
      },
      {
        title: "画像正規化",
        detail: "解析入力向けに画像を整形",
      },
      {
        title: "視覚推論",
        detail: "VLMで特徴抽出を実行",
      },
      {
        title: "構造化解析",
        detail: "抽出結果をJSONへ変換",
      },
    ],
    [],
  );

  const ragSteps = useMemo(
    () => [
      {
        title: "クエリ構築",
        detail: "検索用サマリを生成",
      },
      {
        title: "ベクトル検索",
        detail: "類似事例を取得",
      },
      {
        title: "コンテキスト構築",
        detail: "価格根拠を整理",
      },
      {
        title: "価格推論",
        detail: "LLMでレンジを算出",
      },
    ],
    [],
  );

  const analysisHighlights = useMemo(() => {
    const tags: string[] = [];
    if (description.category) {
      tags.push(`カテゴリ: ${description.category}`);
    }
    if (description.brand) {
      tags.push(`ブランド: ${description.brand}`);
    }
    if (description.model) {
      tags.push(`モデル: ${description.model}`);
    }
    if (description.year) {
      tags.push(`年式: ${description.year}`);
    }
    if (description.condition) {
      tags.push(`状態: ${description.condition}`);
    }
    if (description.materials.length) {
      tags.push(`素材: ${description.materials.slice(0, 2).join("・")}`);
    }
    if (description.features.length) {
      tags.push(`特徴: ${description.features.slice(0, 2).join("・")}`);
    }
    return tags;
  }, [description]);

  const evidenceHighlights = useMemo(
    () => valuation?.evidence.slice(0, 3) ?? [],
    [valuation],
  );

  const consolePools = useMemo(
    () => ({
      idle: [
        "待機中: 画像がアップロードされるのを待っています。",
        "準備完了: VLMエンジンはスタンバイ中。",
        "RAGインデックス: 接続済み。",
        "推論コンテキスト: 初期化済み。",
      ],
      ready: [
        "特徴抽出が完了しました。",
        "必要に応じて手動で調整できます。",
        "必要なら再推論できます。",
      ],
      describing: [
        "画像を正規化しています...",
        "輪郭を検出しています...",
        "材質のテクスチャを解析しています...",
        "状態シグナルを抽出しています...",
        "説明文を構造化しています...",
        "カテゴリ候補を照合しています...",
      ],
      estimating: [
        "特徴をベクトルへ変換...",
        "ベクトルDBにクエリを送信...",
        "近傍結果をマージ中...",
        "価格事例をスコアリング...",
        "推論プロンプトを構築...",
        "価格レンジを合成中...",
      ],
      complete: [
        "推論完了: 価格レンジを算出しました。",
        "エビデンスの整合性を確認済み。",
        "信頼度を評価しました。",
        "提示準備完了。",
      ],
    }),
    [],
  );

  const logFormatters = useMemo(
    () => ({
      "vision.upload_received": () => "画像を受信しました。",
      "vision.image_encoded": () => "画像を正規化しました。",
      "vision.request_sent": () => "VLMへ問い合わせ中...",
      "vision.response_parsed": () => "解析結果を構造化しました。",
      "rag.query_build": () => "検索クエリを構築しています...",
      "rag.retrieve_start": () => "ベクトルDBへ検索中...",
      "rag.retrieve_done": (meta?: Record<string, number | string>) => {
        const count =
          typeof meta?.count === "number"
            ? meta.count
            : Number.parseInt(String(meta?.count ?? ""), 10);
        return Number.isFinite(count)
          ? `類似事例 ${count} 件を取得しました。`
          : "類似事例を取得しました。";
      },
      "rag.context_build": () => "エビデンスを整理しています...",
      "rag.request_sent": () => "推論モデルへ問い合わせています...",
    }),
    [],
  );

  const consoleMode =
    status !== "idle"
      ? status
      : hasValuation
        ? "complete"
        : hasDescription
          ? "ready"
          : "idle";

  const appendConsoleLine = (line: string) => {
    setConsoleLines((prev) => {
      const nextLines = [...prev, line];
      return nextLines.slice(-6);
    });
  };

  const handleStreamEvent = (event: StreamEvent, token: number) => {
    if (token !== streamTokenRef.current) {
      return;
    }

    if (event.type === "log") {
      const formatter = logFormatters[event.code as keyof typeof logFormatters];
      const message = formatter ? formatter(event.meta) : `ログ: ${event.code}`;
      appendConsoleLine(message);
      return;
    }

    if (event.type === "step") {
      if (event.phase === "vision") {
        setVisionState("running");
        if (event.status === "start") {
          setVisionActiveIndex(event.index);
          return;
        }
        setVisionCompleted((prev) => Math.max(prev, event.index + 1));
        setVisionActiveIndex((prev) => (prev === event.index ? -1 : prev));
        if (event.index + 1 >= visionSteps.length) {
          setVisionState("done");
        }
        return;
      }

      if (event.phase === "rag") {
        setRagState("running");
        if (event.status === "start") {
          setRagActiveIndex(event.index);
          return;
        }
        setRagCompleted((prev) => Math.max(prev, event.index + 1));
        setRagActiveIndex((prev) => (prev === event.index ? -1 : prev));
        if (event.index + 1 >= ragSteps.length) {
          setRagState("done");
        }
      }
      return;
    }

    if (event.type === "result") {
      if (event.phase === "vision") {
        setDescription(event.payload as InstrumentDescription);
        setVisionState("done");
        setVisionActiveIndex(-1);
        setVisionCompleted(visionSteps.length);
      } else {
        setValuation(event.payload as ValuationResult);
        setRagState("done");
        setRagActiveIndex(-1);
        setRagCompleted(ragSteps.length);
      }
      return;
    }

    if (event.type === "error") {
      setError(event.message);
      appendConsoleLine(`エラー: ${event.message}`);
    }
  };

  useEffect(() => {
    if (consoleIntervalRef.current !== null) {
      window.clearInterval(consoleIntervalRef.current);
      consoleIntervalRef.current = null;
    }

    if (streamingActive) {
      return;
    }

    const pool = consolePools[consoleMode];
    const seed = pool.slice(0, 4);
    setConsoleLines(seed);

    if (consoleMode === "describing" || consoleMode === "estimating") {
      let index = seed.length;
      consoleIntervalRef.current = window.setInterval(() => {
        setConsoleLines((prev) => {
          const next = pool[index % pool.length];
          index += 1;
          const nextLines = [...prev, next];
          return nextLines.slice(-6);
        });
      }, 650);
    }

    return () => {
      if (consoleIntervalRef.current !== null) {
        window.clearInterval(consoleIntervalRef.current);
        consoleIntervalRef.current = null;
      }
    };
  }, [consoleMode, consolePools, streamingActive]);

  useEffect(() => {
    if (streamingPhase === "vision") {
      clearTimers(visionTimersRef);
      return;
    }

    if (status !== "describing") {
      clearTimers(visionTimersRef);
      setVisionState(hasDescription ? "done" : "idle");
      setVisionActiveIndex(-1);
      setVisionCompleted(hasDescription ? visionSteps.length : 0);
      return;
    }

    clearTimers(visionTimersRef);
    setVisionState("running");
    setVisionActiveIndex(0);
    setVisionCompleted(0);

    visionSteps.forEach((_, index) => {
      const timerId = window.setTimeout(() => {
        setVisionActiveIndex(index);
        setVisionCompleted(index);
      }, 600 * index);
      visionTimersRef.current.push(timerId);
    });

    const finishId = window.setTimeout(() => {
      setVisionActiveIndex(-1);
      setVisionCompleted(visionSteps.length);
      setVisionState("done");
    }, 600 * visionSteps.length + 200);
    visionTimersRef.current.push(finishId);

    return () => {
      clearTimers(visionTimersRef);
    };
  }, [hasDescription, status, streamingPhase, visionSteps]);

  useEffect(() => {
    if (streamingPhase === "rag") {
      clearTimers(ragTimersRef);
      return;
    }

    if (status !== "estimating") {
      clearTimers(ragTimersRef);
      setRagState(hasValuation ? "done" : "idle");
      setRagActiveIndex(-1);
      setRagCompleted(hasValuation ? ragSteps.length : 0);
      return;
    }

    clearTimers(ragTimersRef);
    setRagState("running");
    setRagActiveIndex(0);
    setRagCompleted(0);

    ragSteps.forEach((_, index) => {
      const timerId = window.setTimeout(() => {
        setRagActiveIndex(index);
        setRagCompleted(index);
      }, 600 * index);
      ragTimersRef.current.push(timerId);
    });

    const finishId = window.setTimeout(() => {
      setRagActiveIndex(-1);
      setRagCompleted(ragSteps.length);
      setRagState("done");
    }, 600 * ragSteps.length + 200);
    ragTimersRef.current.push(finishId);

    return () => {
      clearTimers(ragTimersRef);
    };
  }, [hasValuation, ragSteps, status, streamingPhase]);

  const aiState =
    status === "describing"
      ? "scanning"
      : status === "estimating"
        ? "reasoning"
        : hasValuation
          ? "complete"
          : hasDescription
            ? "ready"
            : "idle";

  const aiStatusLabel =
    status === "describing"
      ? "画像解析中"
      : status === "estimating"
        ? "推論中"
        : hasValuation
          ? "推論完了"
          : hasDescription
            ? "解析完了"
            : "待機中";

  const aiStatusDetail =
    status === "describing"
      ? "輪郭・材質・状態を推定し、特徴を構造化しています。"
      : status === "estimating"
        ? "ベクトル検索と類似事例の照合を進めています。"
        : hasValuation
          ? "価格帯と根拠を提示しています。"
          : hasDescription
            ? "必要に応じて特徴を修正し、再推論できます。"
            : "画像をアップロードすると解析が始まります。";

  const activeStepLabel =
    status === "describing"
      ? visionSteps[visionActiveIndex]?.title
      : status === "estimating"
        ? ragSteps[ragActiveIndex]?.title
        : null;

  const imageResolution = imageMeta
    ? `${imageMeta.width} x ${imageMeta.height}`
    : "未解析";
  const aspectRatio = imageMeta
    ? (imageMeta.width / imageMeta.height).toFixed(2)
    : "--";

  const terminalLines = useMemo(() => {
    const statusTone: TerminalLine["tone"] =
      aiState === "complete"
        ? "ok"
        : aiState === "scanning" || aiState === "reasoning"
          ? "accent"
          : "muted";
    const modeLabel = streamingPhase
      ? streamingPhase === "vision"
        ? "視覚"
        : "RAG"
      : "待機";
    const visionProgress = `${visionCompleted}/${visionSteps.length}`;
    const ragProgress = `${ragCompleted}/${ragSteps.length}`;

    const lines: TerminalLine[] = [
      {
        prefix: "#",
        tone: "accent",
        text: "AI推論ターミナル / VAL-CORE v1.8.2",
      },
      {
        prefix: "$",
        tone: statusTone,
        text: `状態 ${aiStatusLabel} | モード ${modeLabel}`,
      },
      {
        prefix: "$",
        text: `入力 ${file ? file.name : "未選択"} | ${file?.type || "未設定"} | ${
          file ? formatFileSize(file.size) : "--"
        }`,
      },
      {
        prefix: "$",
        text: `画像 ${imageResolution} | 比率 ${aspectRatio}`,
      },
      {
        prefix: "$",
        text: `視覚 ${formatPipelineStatus(visionState)} ${visionProgress}${
          status === "describing" && activeStepLabel ? ` | ${activeStepLabel}` : ""
        }`,
      },
      {
        prefix: "$",
        text: `RAG ${formatPipelineStatus(ragState)} ${ragProgress}${
          status === "estimating" && activeStepLabel ? ` | ${activeStepLabel}` : ""
        }`,
      },
      analysisHighlights.length
        ? {
            prefix: "$",
            text: `特徴 ${analysisHighlights.slice(0, 3).join(" / ")}`,
          }
        : { prefix: "$", tone: "muted", text: "特徴 未取得" },
      evidenceHighlights.length
        ? {
            prefix: "$",
            text: `参照 ${evidenceHighlights.slice(0, 2).join(" / ")}`,
          }
        : { prefix: "$", tone: "muted", text: "参照 未取得" },
      { prefix: ">", tone: "muted", text: "ログストリーム" },
      ...consoleLines.map<TerminalLine>((line) => ({
        prefix: ">",
        text: line,
      })),
    ];

    return lines;
  }, [
    activeStepLabel,
    aiState,
    aiStatusLabel,
    analysisHighlights,
    aspectRatio,
    consoleLines,
    evidenceHighlights,
    file,
    imageResolution,
    ragCompleted,
    ragState,
    ragSteps.length,
    status,
    streamingPhase,
    visionCompleted,
    visionState,
    visionSteps.length,
  ]);

  const primaryLabel =
    status === "describing"
      ? "解析中..."
      : status === "estimating"
        ? "推論中..."
        : "解析と推論を開始";

  const updateField = <K extends keyof InstrumentDescription>(
    key: K,
    value: InstrumentDescription[K],
  ) => {
    setDescription((prev) => ({ ...prev, [key]: value }));
  };

  const handleDescribe = async () => {
    if (!file) {
      setError("画像を選択してください。");
      return;
    }

    autoEstimateRef.current = true;
    const token = streamTokenRef.current + 1;
    streamTokenRef.current = token;
    describeAbortRef.current?.abort();
    const controller = new AbortController();
    describeAbortRef.current = controller;

    setStatus("describing");
    setError(null);
    setValuation(null);
    setStreamingActive(true);
    setStreamingPhase("vision");
    setVisionState("running");
    setVisionActiveIndex(-1);
    setVisionCompleted(0);
    setConsoleLines(["ストリーム接続中..."]);

    let receivedEvent = false;
    let shouldAutoEstimate = false;
    try {
      await streamDescribe(
        file,
        (event) => {
          receivedEvent = true;
          if (event.type === "result" && event.phase === "vision") {
            shouldAutoEstimate = true;
          }
          handleStreamEvent(event, token);
        },
        controller.signal,
      );

      if (!receivedEvent) {
        throw new Error("Stream ended");
      }
    } catch (err) {
      if (controller.signal.aborted || token !== streamTokenRef.current) {
        return;
      }

      setStreamingActive(false);
      setStreamingPhase(null);

      if (!receivedEvent) {
        try {
          const result = await describeInstrument(file);
          setDescription(result);
          shouldAutoEstimate = true;
          return;
        } catch (fallbackError) {
          setError(
            fallbackError instanceof Error
              ? fallbackError.message
              : "解析に失敗しました。",
          );
        }
      }

      setError(err instanceof Error ? err.message : "解析に失敗しました。");
    } finally {
      if (token === streamTokenRef.current) {
        setStreamingActive(false);
        setStreamingPhase(null);
        setStatus("idle");
      }
      if (!shouldAutoEstimate) {
        autoEstimateRef.current = false;
      }
    }
  };

  const handleEstimate = async () => {
    const token = streamTokenRef.current + 1;
    streamTokenRef.current = token;
    estimateAbortRef.current?.abort();
    const controller = new AbortController();
    estimateAbortRef.current = controller;

    setStatus("estimating");
    setError(null);
    setStreamingActive(true);
    setStreamingPhase("rag");
    setRagState("running");
    setRagActiveIndex(-1);
    setRagCompleted(0);
    setConsoleLines(["ストリーム接続中..."]);

    let receivedEvent = false;
    try {
      await streamEstimate(
        description,
        (event) => {
          receivedEvent = true;
          handleStreamEvent(event, token);
        },
        controller.signal,
      );

      if (!receivedEvent) {
        throw new Error("Stream ended");
      }
    } catch (err) {
      if (controller.signal.aborted || token !== streamTokenRef.current) {
        return;
      }

      setStreamingActive(false);
      setStreamingPhase(null);

      if (!receivedEvent) {
        try {
          const result = await estimateValue(description);
          setValuation(result);
          return;
        } catch (fallbackError) {
          setError(
            fallbackError instanceof Error
              ? fallbackError.message
              : "見積もりに失敗しました。",
          );
        }
      }

      setError(err instanceof Error ? err.message : "見積もりに失敗しました。");
    } finally {
      if (token === streamTokenRef.current) {
        setStreamingActive(false);
        setStreamingPhase(null);
        setStatus("idle");
      }
    }
  };

  useEffect(() => {
    if (!autoEstimateRef.current) {
      return;
    }
    if (status !== "idle") {
      return;
    }
    if (!hasDescription) {
      return;
    }
    autoEstimateRef.current = false;
    void handleEstimate();
  }, [hasDescription, status]);

  return (
    <div className="page">
      <header className="hero">
        <p className="eyebrow">中古楽器バリュエーション</p>
        <h1>中古楽器 価格査定AIエージェント</h1>
        <p className="lead">
          画像から特徴を抽出し、市場データに基づいた参考価格を提示します。
        </p>
      </header>

      <main className="content">
        <section className="panel upload-panel">
          <div className="panel-header">
            <h2>1. 画像をアップロード</h2>
            <p>画像を選択したらワンクリックで解析と推論を実行します。</p>
          </div>
          <label className="upload">
            <input
              type="file"
              accept="image/*"
              onChange={(event) => {
                const selected = event.target.files?.[0] ?? null;
                setFile(selected);
              }}
            />
            <span>画像を選択</span>
          </label>
          {previewUrl ? (
            <div className="preview">
              <img src={previewUrl} alt="アップロード画像" />
            </div>
          ) : (
            <div className="preview placeholder">プレビューがここに表示されます。</div>
          )}
          <button
            className="primary"
            onClick={handleDescribe}
            disabled={status !== "idle" || !file}
          >
            {primaryLabel}
          </button>
        </section>

        <section className={`panel ai-panel ${aiState}`}>
          <div className="panel-header">
            <h2>2. 推論ターミナル</h2>
            <p>AIの処理を端末ログとしてライブ表示します。</p>
          </div>
          <div className="terminal-shell">
            <div className="terminal-titlebar">
              <div className="terminal-dots" aria-hidden="true">
                <span className="terminal-dot" />
                <span className="terminal-dot" />
                <span className="terminal-dot" />
              </div>
              <span className="terminal-title">AI推論コンソール</span>
              <span className="terminal-status">{aiStatusLabel}</span>
            </div>
            <div className="terminal-body">
              <ul className="terminal-lines">
                {terminalLines.map((line, index) => (
                  <li
                    key={`${line.text}-${index}`}
                    className={`terminal-line ${line.tone ?? ""}`}
                  >
                    <span className="terminal-prefix">{line.prefix ?? "$"}</span>
                    <span className="terminal-text">{line.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <p className="terminal-footnote">{aiStatusDetail}</p>
        </section>

        <section className="panel edit-panel">
          <div className="panel-header">
            <h2>3. 特徴を確認（任意）</h2>
            <p>必要に応じて編集し、再推論できます。</p>
          </div>
          <div className="grid">
            <label>
              カテゴリ
              <input
                value={description.category}
                onChange={(event) => updateField("category", event.target.value)}
                placeholder="例: アコースティックギター"
              />
            </label>
            <label>
              ブランド
              <input
                value={description.brand}
                onChange={(event) => updateField("brand", event.target.value)}
                placeholder="例: Yamaha"
              />
            </label>
            <label>
              モデル
              <input
                value={description.model}
                onChange={(event) => updateField("model", event.target.value)}
                placeholder="例: FG-180"
              />
            </label>
            <label>
              年式
              <input
                value={description.year ?? ""}
                onChange={(event) =>
                  updateField("year", event.target.value || null)
                }
                placeholder="例: 1974"
              />
            </label>
            <label>
              状態
              <input
                value={description.condition}
                onChange={(event) => updateField("condition", event.target.value)}
                placeholder="例: 目立つ傷なし"
              />
            </label>
            <label>
              素材
              <input
                value={description.materials.join(", ")}
                onChange={(event) =>
                  updateField(
                    "materials",
                    event.target.value
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean),
                  )
                }
                placeholder="例: スプルース, ローズウッド"
              />
            </label>
          </div>
          <label className="stack">
            特徴
            <textarea
              value={description.features.join("\n")}
              onChange={(event) =>
                updateField(
                  "features",
                  event.target.value
                    .split("\n")
                    .map((item) => item.trim())
                    .filter(Boolean),
                )
              }
              placeholder="特徴を箇条書きで入力"
              rows={4}
            />
          </label>
          <label className="stack">
            メモ
            <textarea
              value={description.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              placeholder="付属品、修理歴、シリアルなど"
              rows={3}
            />
          </label>
          <button
            className="primary"
            onClick={handleEstimate}
            disabled={status !== "idle" || !hasDescription}
          >
            {status === "estimating" ? "推論中..." : "修正後に再推論"}
          </button>
        </section>

        <section className="panel result-panel">
          <div className="panel-header">
            <h2>4. 見積もり結果</h2>
            <p>RAGの取得結果とLLM推論に基づく参考値です。</p>
          </div>
          {valuation ? (
            <div className="result">
              <div>
                <span className="label">想定価格</span>
                <strong>{formatCurrency(valuation.price_jpy)}</strong>
              </div>
              <div>
                <span className="label">レンジ</span>
                <strong>
                  {formatCurrency(valuation.range_jpy[0])} -{" "}
                  {formatCurrency(valuation.range_jpy[1])}
                </strong>
              </div>
              <div>
                <span className="label">信頼度</span>
                <strong>{Math.round(valuation.confidence * 100)}%</strong>
              </div>
              <div className="detail">
                <span className="label">根拠</span>
                <p>{valuation.rationale}</p>
              </div>
              <div className="detail">
                <span className="label">参照情報</span>
                <ul>
                  {valuation.evidence.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <div className="result placeholder">
              解析後に見積もり結果が表示されます。
            </div>
          )}
          {error ? <p className="error">{error}</p> : null}
        </section>
      </main>
    </div>
  );
}

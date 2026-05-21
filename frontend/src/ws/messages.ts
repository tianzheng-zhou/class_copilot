import type { AnswerType, QuestionSource } from "@/api/types";

// ===== Outbound (client -> server) =====

export interface OutboundMessages {
  start_listening: {
    course_id: string;
    auto_stop_seconds?: number;
    auto_stop_label?: string;
  };
  stop_listening: Record<string, never>;
  manual_detect: Record<string, never>;
  force_answer: Record<string, never>;
  chat: {
    question: string;
    model: "fast" | "quality" | null;
    enable_thinking: boolean;
  };
  update_auto_stop: {
    seconds: number;
    label?: string;
  };
}

export type OutboundMessageType = keyof OutboundMessages;

// ===== Inbound (server -> client) =====

export type ConnectionStatus = "ready" | "listening" | "stopped" | "error";

export interface StatusEventData {
  status: ConnectionStatus;
  session_id: string | null;
  course_id: string | null;
  course_name: string | null;
  is_listening: boolean;
  auto_stop_remaining: number;
}

export interface TranscriptionEventData {
  session_id: string;
  text: string;
  is_final: boolean;
  start_time: number;
  end_time: number;
  sequence: number;
}

export interface QuestionDetectedData {
  question_id: string;
  question_text: string;
  source: QuestionSource;
  confidence: number;
  context_text: string | null;
}

export interface AnswerGeneratingData {
  question_id: string;
  answer_type: AnswerType;
}

export interface AnswerChunkData {
  question_id: string;
  answer_type: AnswerType;
  chunk: string;
  full_text: string;
}

export interface AnswerCompleteData {
  question_id: string;
  answer_type: AnswerType;
  content: string;
}

export interface ChatChunkData {
  chunk: string;
  full_text: string;
}

export interface ChatCompleteData {
  content: string;
  model_used: string;
}

export interface MicLevelData {
  db: number;
  peak: number;
  clipping: boolean;
}

export interface AutoStopTickData {
  remaining: number;
}

export type NotificationLevel = "info" | "warning" | "error";

export interface NotificationData {
  level: NotificationLevel;
  message: string;
}

export type ErrorCode =
  | "asr_permanent"
  | "asr_unavailable"
  | "transcript_no_output_timeout"
  | "stop_failed"
  | "audio_device"
  | "config_missing"
  | "bad_request"
  | "internal"
  | string;

export interface ErrorEventData {
  code: ErrorCode;
  message: string;
  detail?: string;
}

export interface InboundMessages {
  status: StatusEventData;
  transcription: TranscriptionEventData;
  question_detected: QuestionDetectedData;
  answer_generating: AnswerGeneratingData;
  answer_chunk: AnswerChunkData;
  answer_complete: AnswerCompleteData;
  chat_chunk: ChatChunkData;
  chat_complete: ChatCompleteData;
  mic_level: MicLevelData;
  auto_stop_tick: AutoStopTickData;
  notification: NotificationData;
  error: ErrorEventData;
}

export type InboundMessageType = keyof InboundMessages;

export type InboundEvent = {
  [K in InboundMessageType]: { type: K; data: InboundMessages[K] };
}[InboundMessageType];

// Status carries server-side session state, separate from connection liveness
export type ServerStatus = ConnectionStatus;

// Connection status of the WebSocket itself (frontend-only concept)
export type WsConnectionState = "connecting" | "open" | "closed";

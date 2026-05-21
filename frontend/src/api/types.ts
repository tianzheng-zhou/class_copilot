// Mirror of contract.md §2

export type SessionStatus = "active" | "stopped" | "interrupted";
export type QuestionSource = "auto" | "manual";
export type AnswerType = "brief" | "detailed";
export type ChatRole = "user" | "assistant";
export type Language = "zh" | "en";
export type OutputLanguage = "zh" | "en" | "bilingual";
export type AudioSource = "microphone" | "loopback" | "file";
export type AsrModel = "qwen3.5-omni-flash-realtime" | "qwen3.5-omni-plus-realtime";
export type AnswerModel = "qwen3.5-flash" | "qwen3.5-plus";

export interface Course {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface SessionListItem {
  id: string;
  course_id: string;
  course_name: string | null;
  custom_name: string | null;
  date: string;
  started_at: string;
  ended_at: string | null;
  status: SessionStatus;
}

export interface TranscriptionItem {
  id: string;
  sequence: number;
  start_time: number;
  end_time: number;
  text: string;
  is_final: boolean;
  created_at: string;
}

export interface AnswerItem {
  id: string;
  answer_type: AnswerType;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface QuestionItem {
  id: string;
  question_text: string;
  source: QuestionSource;
  confidence: number;
  context_text: string | null;
  created_at: string;
  answers: AnswerItem[];
}

export interface ChatMessageItem {
  id: string;
  role: ChatRole;
  content: string;
  model_used: string | null;
  created_at: string;
}

export interface SessionDetail {
  session: SessionListItem & {
    recording_path: string | null;
    recording_duration_seconds: number | null;
    recording_file_size_bytes: number | null;
  };
  transcriptions: TranscriptionItem[];
  questions: QuestionItem[];
  chat_messages: ChatMessageItem[];
}

export interface RuntimeSettings {
  dashscope_api_key: string;
  dashscope_api_key_set: boolean;
  debug_audio_file: boolean;
  language: Language;
  asr_language: OutputLanguage;
  auto_answer_language: OutputLanguage;
  auto_answer_model: AnswerModel;
  chat_language: OutputLanguage;
  auto_answer_type: AnswerType;
  asr_model: AsrModel;
  chat_model_default: string;
  chat_model_fast: string;
  vad_threshold: number;
  vad_prefix_padding_ms: number;
  vad_silence_duration_ms: number;
  asr_session_rotate_minutes: number;
  vad_max_segment_seconds: number;
  transcript_no_output_timeout_minutes: number;
  question_confidence_threshold: number;
  question_cooldown_seconds: number;
  question_similarity_threshold: number;
  audio_source: AudioSource;
  audio_device_id: number | string | null;
  audio_file_path: string;
}

export type SettingsPatch = Partial<{
  dashscope_api_key: string;
  language: Language;
  asr_language: OutputLanguage;
  auto_answer_language: OutputLanguage;
  auto_answer_model: AnswerModel;
  chat_language: OutputLanguage;
  auto_answer_type: AnswerType;
  asr_model: AsrModel;
  chat_model_default: string;
  chat_model_fast: string;
  vad_threshold: number;
  vad_prefix_padding_ms: number;
  vad_silence_duration_ms: number;
  asr_session_rotate_minutes: number;
  vad_max_segment_seconds: number;
  transcript_no_output_timeout_minutes: number;
  question_confidence_threshold: number;
  question_cooldown_seconds: number;
  question_similarity_threshold: number;
  audio_source: AudioSource;
  audio_device_id: number | string | null;
  audio_file_path: string;
}>;

export interface MicrophoneDevice {
  index: number;
  name: string;
  channels: number;
  sample_rate: number;
  is_default: boolean;
}

export interface LoopbackDevice {
  id: string;
  name: string;
  is_default: boolean;
}

export interface AudioDevicesResponse {
  microphone: {
    devices: MicrophoneDevice[];
    current_index: number | null;
  };
  loopback: {
    available: boolean;
    devices: LoopbackDevice[];
    current_id: string | null;
  };
  audio_source: AudioSource;
}

export interface ApiErrorBody {
  detail: string;
}

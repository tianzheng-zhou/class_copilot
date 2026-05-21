import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Slider } from "@/components/ui/Slider";
import { Input } from "@/components/ui/Input";
import { useSettingsStore } from "@/stores/settings";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { Mic2 } from "lucide-react";
import type { SettingsPatch } from "@/api/types";
import { useI18n, tpl } from "@/i18n";

export function AsrParamsSection() {
  const settings = useSettingsStore((state) => state.settings);
  const patchLocal = useSettingsStore((state) => state.patchLocal);
  const update = useSettingsStore((state) => state.update);
  const { t } = useI18n();

  const debouncedUpdate = useDebouncedCallback((partial: SettingsPatch) => {
    void update(partial);
  }, 500);

  if (!settings) return null;

  const onChange = <K extends keyof SettingsPatch>(key: K, value: SettingsPatch[K]) => {
    patchLocal({ [key]: value } as never);
    debouncedUpdate({ [key]: value } as SettingsPatch);
  };

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Mic2 size={14} />
            {t.asr_title}
          </span>
        }
        description={t.asr_desc}
      />
      <CardBody className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <Field
          label={t.asr_vad_threshold}
          hint={tpl(t.asr_vad_threshold_hint, { value: settings.vad_threshold.toFixed(2) })}
        >
          <Slider
            min={0}
            max={1}
            step={0.05}
            value={settings.vad_threshold}
            onChange={(value) => onChange("vad_threshold", Number(value.toFixed(2)))}
          />
        </Field>
        <Field label={t.asr_vad_prefix}>
          <Input
            type="number"
            min={0}
            value={settings.vad_prefix_padding_ms}
            onChange={(event) =>
              onChange("vad_prefix_padding_ms", Math.max(0, Number(event.target.value)))
            }
          />
        </Field>
        <Field label={t.asr_vad_silence}>
          <Input
            type="number"
            min={0}
            value={settings.vad_silence_duration_ms}
            onChange={(event) =>
              onChange("vad_silence_duration_ms", Math.max(0, Number(event.target.value)))
            }
          />
        </Field>
        <Field label={t.asr_session_rotate}>
          <Input
            type="number"
            min={1}
            step={0.5}
            value={settings.asr_session_rotate_minutes}
            onChange={(event) =>
              onChange("asr_session_rotate_minutes", Math.max(1, Number(event.target.value)))
            }
          />
        </Field>
        <Field label={t.asr_max_segment}>
          <Input
            type="number"
            min={0}
            step={1}
            value={settings.vad_max_segment_seconds}
            onChange={(event) =>
              onChange("vad_max_segment_seconds", Math.max(0, Number(event.target.value)))
            }
          />
        </Field>
        <Field label={t.asr_no_output_timeout} hint={t.asr_no_output_timeout_hint}>
          <Input
            type="number"
            min={0}
            step={0.5}
            value={settings.transcript_no_output_timeout_minutes}
            onChange={(event) =>
              onChange(
                "transcript_no_output_timeout_minutes",
                Math.max(0, Number(event.target.value)),
              )
            }
          />
        </Field>
      </CardBody>
    </Card>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="label">{label}</label>
      {children}
      {hint ? <span className="text-xs text-slate-500 dark:text-slate-400">{hint}</span> : null}
    </div>
  );
}

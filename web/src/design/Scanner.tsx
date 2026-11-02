// Camera barcode / QR scanner: BarcodeDetector when the browser has it, else @zxing/browser (loaded on demand).
// Vibrates on a read. Typing the code stays possible (no camera, desktop).
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from './Button';
import { Input } from './Field';

interface Detector {
  detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]>;
}
declare global {
  interface Window {
    BarcodeDetector?: new (o?: { formats?: string[] }) => Detector;
  }
}

export function Scanner({ onCode, onClose, formats, title, last }: {
  onCode: (code: string) => void; onClose: () => void; formats?: string[]; title?: string; last?: string;
}) {
  const { t } = useTranslation();
  const video = useRef<HTMLVideoElement>(null);
  const [noCamera, setNoCamera] = useState(false);
  const [typed, setTyped] = useState('');
  const onCodeRef = useRef(onCode);
  onCodeRef.current = onCode;

  useEffect(() => {
    let stop = () => {};
    let cancelled = false;
    let lastCode = '';
    let lastAt = 0;
    const hit = (code: string) => {
      const now = Date.now();
      if (code === lastCode && now - lastAt < 1500) return;
      lastCode = code;
      lastAt = now;
      navigator.vibrate?.(60);
      onCodeRef.current(code);
    };
    (async () => {
      if (!navigator.mediaDevices?.getUserMedia) return setNoCamera(true);
      try {
        if (window.BarcodeDetector) {
          const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
          if (cancelled) return stream.getTracks().forEach((x) => x.stop());
          const v = video.current!;
          v.srcObject = stream;
          await v.play();
          const det = new window.BarcodeDetector(formats ? { formats } : undefined);
          let timer = 0;
          const tick = async () => {
            try {
              const found = await det.detect(v);
              if (found[0]?.rawValue) hit(found[0].rawValue);
            } catch {
              /* frame not ready */
            }
            timer = window.setTimeout(tick, 250);
          };
          void tick();
          stop = () => { clearTimeout(timer); stream.getTracks().forEach((x) => x.stop()); };
        } else {
          const { BrowserMultiFormatReader } = await import('@zxing/browser');
          const reader = new BrowserMultiFormatReader();
          const controls = await reader.decodeFromVideoDevice(undefined, video.current!, (r) => r && hit(r.getText()));
          if (cancelled) controls.stop();
          stop = () => controls.stop();
        }
      } catch {
        setNoCamera(true);
      }
    })();
    return () => {
      cancelled = true;
      stop();
    };
  }, [formats]);

  return (
    <div className="flex flex-col gap-3 rounded-[20px] bg-[#0B0F0F] p-4 text-white">
      <div className="flex items-center justify-between text-[13px]">
        <button type="button" onClick={onClose} aria-label={t('action.close')} className="p-1">✕</button>
        <b>{title ?? t('scanner.title')}</b>
        <span className="w-6" />
      </div>
      <div className="relative flex h-[240px] items-center justify-center overflow-hidden rounded-xl bg-[repeating-linear-gradient(135deg,#1A2222_0_8px,#202A2A_8px_16px)]">
        {!noCamera && <video ref={video} className="absolute inset-0 size-full object-cover" muted playsInline />}
        <div className="pointer-events-none relative h-[110px] w-[200px]">
          <span className="absolute top-0 left-0 size-6 rounded-tl border-t-[3px] border-l-[3px] border-posdark-accent" />
          <span className="absolute top-0 right-0 size-6 rounded-tr border-t-[3px] border-r-[3px] border-posdark-accent" />
          <span className="absolute bottom-0 left-0 size-6 rounded-bl border-b-[3px] border-l-[3px] border-posdark-accent" />
          <span className="absolute right-0 bottom-0 size-6 rounded-br border-r-[3px] border-b-[3px] border-posdark-accent" />
          <span className="absolute top-[54px] right-3 left-3 h-0.5 bg-[#FF5A4E]" />
        </div>
        {noCamera && <span className="absolute bottom-2 px-4 text-center text-[12px] text-posdark-text-subtle">{t('scanner.noCamera')}</span>}
      </div>
      {last && <div className="rounded-[10px] bg-posdark-raised px-3 py-2.5 text-[13px]">{last}</div>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) { onCode(typed.trim()); setTyped(''); } }}>
        <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t('scanner.hint')} className="text-neutral-900" aria-label={t('scanner.title')} />
        <Button type="submit" variant="primary">{t('action.use')}</Button>
      </form>
    </div>
  );
}

import { toPng } from 'html-to-image';

export interface ExportOptions {
  fileName: string;
  elementId: string;
  scenarioTitle: string;
  timeSeconds: number;
  isReplay?: boolean;
}

export async function exportComponentPng({
  fileName,
  elementId,
  scenarioTitle,
  timeSeconds,
  isReplay = false,
}: ExportOptions): Promise<void> {
  const element = document.getElementById(elementId);
  if (!element) {
    console.error(`Export failed: element #${elementId} not found`);
    return;
  }

  // Create overlay watermark header banner to ensure caption and honesty badge are burned into PNG
  const watermarkDiv = document.createElement('div');
  watermarkDiv.className = 'export-watermark';
  watermarkDiv.style.cssText = `
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    background: #0F0720;
    color: #F4F0FF;
    padding: 10px 18px;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid rgba(255, 255, 255, 0.12);
    z-index: 99999;
  `;

  const badgeText = isReplay
    ? 'REPLAY OF RECORDED TELEMETRY; risk and remediation simulated'
    : 'SIMULATED DATA - control plane not yet implemented';

  const badgeColor = isReplay ? '#60A5FA' : '#FFB347';
  const badgeBg = isReplay ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255, 179, 71, 0.15)';

  watermarkDiv.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      <span style="font-weight: 700; color: #6D4AFF; letter-spacing: -0.3px;">MeshHeal AI</span>
      <span style="color: #A99BC9;">|</span>
      <span style="color: #F4F0FF; font-weight: 500;">Scenario: ${scenarioTitle} (t=${Math.round(timeSeconds)}s)</span>
    </div>
    <div style="background: ${badgeBg}; color: ${badgeColor}; border: 1px solid ${badgeColor}; border-radius: 9999px; padding: 3px 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600;">
      [${badgeText}]
    </div>
  `;

  // Temporarily attach watermark and adjust padding
  const originalPosition = element.style.position;
  const originalPaddingTop = element.style.paddingTop;
  element.style.position = 'relative';
  element.style.paddingTop = '46px';
  element.prepend(watermarkDiv);

  try {
    const isLight = document.documentElement.classList.contains('light');
    const dataUrl = await toPng(element, {
      pixelRatio: 2, // 2x scale
      cacheBust: true,
      backgroundColor: isLight ? '#F6F3FF' : '#0F0720',
    });

    const link = document.createElement('a');
    link.download = `${fileName}_t${Math.round(timeSeconds)}s.png`;
    link.href = dataUrl;
    link.click();
  } catch (err) {
    console.error('PNG export failed:', err);
  } finally {
    watermarkDiv.remove();
    element.style.position = originalPosition;
    element.style.paddingTop = originalPaddingTop;
  }
}

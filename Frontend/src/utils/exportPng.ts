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

  // Create overlay watermark header/banner clone to ensure caption and honesty badge are burned in
  const watermarkDiv = document.createElement('div');
  watermarkDiv.className = 'export-watermark';
  watermarkDiv.style.cssText = `
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    background: #0B1020;
    color: #E6EBF5;
    padding: 8px 14px;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #22304F;
    z-index: 99999;
  `;

  const badgeText = isReplay
    ? 'REPLAY OF RECORDED TELEMETRY; risk and remediation simulated'
    : 'SIMULATED DATA - control plane not yet implemented';

  const badgeColor = isReplay ? '#60A5FA' : '#FBBF24';
  const badgeBg = isReplay ? 'rgba(59, 130, 246, 0.15)' : 'rgba(245, 158, 11, 0.15)';

  watermarkDiv.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      <span style="font-weight: 700; color: #6EA8FF; letter-spacing: -0.3px;">MeshHeal AI</span>
      <span style="color: #8FA0C0;">|</span>
      <span style="color: #E6EBF5; font-weight: 500;">Scenario: ${scenarioTitle} (t=${Math.round(timeSeconds)}s)</span>
    </div>
    <div style="background: ${badgeBg}; color: ${badgeColor}; border: 1px solid ${badgeColor}; border-radius: 4px; padding: 2px 8px; font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600;">
      [${badgeText}]
    </div>
  `;

  // Temporarily attach watermark and adjust padding
  const originalPosition = element.style.position;
  const originalPaddingTop = element.style.paddingTop;
  element.style.position = 'relative';
  element.style.paddingTop = '40px';
  element.prepend(watermarkDiv);

  try {
    const dataUrl = await toPng(element, {
      pixelRatio: 2, // 2x scale
      cacheBust: true,
      backgroundColor: document.documentElement.classList.contains('light') ? '#FFFFFF' : '#0B1020',
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

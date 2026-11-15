// Shared draw loop for the two 3D canvases (planet and body).
// Resizes to the screen, pauses when the canvas is not visible, and
// draws a single frame if the user asks for reduced motion.

export function stage(canvas, draw) {
  const ctx = canvas.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0, h = 0, visible = true;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (still && w && h) draw(ctx, w, h, 0);
  };
  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(canvas);
  resize();

  const loop = (ms) => {
    if (visible && w && h) draw(ctx, w, h, ms / 1000);
    requestAnimationFrame(loop);
  };
  if (!still) requestAnimationFrame(loop);

  return { redraw: () => w && h && draw(ctx, w, h, performance.now() / 1000) };
}

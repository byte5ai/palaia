/* Window frame for the Omadia canvas — traffic lights, status bar, prompt bar */

function CanvasFrame({ children, prompt = '', onPromptChange, onSpotlight, statusText, hidePrompt }) {
  return (
    <div className="omadia-window">
      <div className="traffic-lights">
        <div className="traffic-light tl-close" />
        <div className="traffic-light tl-min" />
        <div className="traffic-light tl-max" />
      </div>

      <div className="status-bar">
        <span className="brand">omadia</span>
        <span className="indicators">
          {statusText || (<>
            <span className="live-dot" />10 connectors live <span style={{ margin: '0 6px' }}>·</span>
            2 resolving <span style={{ margin: '0 6px' }}>·</span>
            Mon <span style={{ margin: '0 6px' }}>·</span>
            18 May <span style={{ margin: '0 6px' }}>·</span>
            09:42
          </>)}
        </span>
      </div>

      <div className="canvas-area">
        {children}
        {!hidePrompt && (
          <div className="prompt-bar-wrap">
            <div className="prompt-bar" onClick={onSpotlight}>
              <input
                placeholder="Ask anything. The canvas will answer."
                value={prompt}
                onChange={(e) => onPromptChange && onPromptChange(e.target.value)}
                onFocus={(e) => { e.target.blur(); onSpotlight && onSpotlight(); }}
              />
              <span className="hints">⌘K · ⌘↩</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

window.CanvasFrame = CanvasFrame;

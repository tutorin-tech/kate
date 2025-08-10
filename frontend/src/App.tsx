import { useState, useEffect, useRef, type KeyboardEvent } from "react";

const ESC = "\x1b";

const SPECIAL_KEY_MAP: Record<string, string> = {
  Tab: "\x09",
  Backspace: "\x7f",
  Escape: ESC,
  Home: ESC + "[1~",
  Insert: ESC + "[2~",
  Delete: ESC + "[3~",
  End: ESC + "[4~",
  PageUp: ESC + "[5~",
  PageDown: ESC + "[6~",
  ArrowUp: ESC + "[A",
  ArrowDown: ESC + "[B",
  ArrowRight: ESC + "[C",
  ArrowLeft: ESC + "[D",
  F1: ESC + "[[A",
  F2: ESC + "[[B",
  F3: ESC + "[[C",
  F4: ESC + "[[D",
  F5: ESC + "[[E",
  F6: ESC + "[17~",
  F7: ESC + "[18~",
  F8: ESC + "[19~",
  F9: ESC + "[20~",
  F10: ESC + "[21~",
  F11: ESC + "[23~",
  F12: ESC + "[24~",
  Enter: "\r",
};

const CTRL_KEY_MAP: Record<string, string> = {
  "[": "\x1b",
  "\\": "\x1c",
  "]": "\x1d",
  "^": "\x1e",
  _: "\x1f",
  "@": "\x00",
};

function getCtrlChar(key: string): string | null {
  const code = key.toUpperCase().charCodeAt(0);
  if (code >= 65 && code <= 90) {
    // Using ASCII codes for the letters A-Z,
    // calculate the ASCII codes for the control
    // characters Ctrl-A through Ctrl-Z.
    return String.fromCharCode(code - 64); // Ctrl-A..Z
  }
  return null;
}

function App() {
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [content, setContent] = useState("");
  const terminalRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const connection = new WebSocket("ws://localhost:8080/termsocket");
    setWs(connection);
    connection.onmessage = (event) => setContent(event.data);

    return () => {
      connection.close();
    };
  }, []);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.focus();
    }
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLPreElement>) {
    const { key, ctrlKey, altKey, shiftKey } = event;

    let output: string | null = null;

    if (ctrlKey && !altKey && !shiftKey && /^[A-Za-z]$/.test(key)) {
      output = getCtrlChar(key);
    } else if (ctrlKey && !altKey && !shiftKey && key in CTRL_KEY_MAP) {
      output = CTRL_KEY_MAP[key];
    } else if (key in SPECIAL_KEY_MAP) {
      output = SPECIAL_KEY_MAP[key];
    } else if (!ctrlKey && !altKey && key.length === 1) {
      output = key;
    }

    if (output) {
      ws?.send(output);
      event.preventDefault();
    }
  }

  return (
    <pre
      className="terminal-display"
      ref={terminalRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      dangerouslySetInnerHTML={{ __html: content }}
    />
  );
}

export default App;

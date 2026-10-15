import { useState, type ReactNode } from 'react'
import { parseTelegramHtml, type Node } from '../pages/richtext'

function Spoiler({ children }: { children: ReactNode }) {
  const [shown, setShown] = useState(false)
  return (
    <span className={`tg-spoiler${shown ? ' tg-spoiler-open' : ''}`} role="button" tabIndex={0}
      onClick={() => setShown((v) => !v)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShown((v) => !v) } }}>
      {children}
    </span>
  )
}

function render(nodes: Node[], keyPrefix = ''): ReactNode[] {
  return nodes.map((n, i) => {
    const key = `${keyPrefix}${i}`
    if (n.kind === 'text') return n.text
    const kids = render(n.children, `${key}.`)
    switch (n.tag) {
      case 'b': return <strong key={key}>{kids}</strong>
      case 'i': return <em key={key}>{kids}</em>
      case 'u': return <u key={key}>{kids}</u>
      case 's': return <s key={key}>{kids}</s>
      case 'code': return <code key={key}>{kids}</code>
      case 'pre': return <pre key={key}>{kids}</pre>
      case 'a': return <a key={key} href={n.href} target="_blank" rel="noopener noreferrer nofollow">{kids}</a>
      case 'spoiler': return <Spoiler key={key}>{kids}</Spoiler>
      case 'emoji': return <span key={key} className="tg-emoji">{kids}</span>
    }
  })
}

/** Telegram HTML matnini xavfsiz (React elementlari bilan) ko'rsatadi. */
export function TelegramText({ html }: { html: string }) {
  return <div className="tg-text">{render(parseTelegramHtml(html))}</div>
}

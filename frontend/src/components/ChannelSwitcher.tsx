import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useActiveChannel } from '../context/ChannelContext'
import type { Channel } from '../api/channels'

interface ChannelSwitcherProps {
  onSelect?: () => void
}

export function ChannelSwitcher({ onSelect }: ChannelSwitcherProps) {
  const { channels, activeChannelId, activeChannel, setActiveChannelId, loading } =
    useActiveChannel()
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Dışarı tıklandığında veya Escape'e basıldığında menüyü kapat
  useEffect(() => {
    if (!isOpen) return

    function handleMouseDown(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  function handleSelect(ch: Channel) {
    setActiveChannelId(ch.id)
    setIsOpen(false)
    if (onSelect) {
      onSelect()
    }
  }

  if (loading && channels.length === 0) {
    return (
      <div className="channel-switcher channel-switcher--loading">
        <div className="channel-switcher-skeleton" />
      </div>
    )
  }

  if (channels.length === 0) {
    return (
      <div className="channel-switcher">
        <Link
          to="/kanallar"
          className="channel-switcher-empty-btn"
          onClick={onSelect}
          title="Kanal bağlamak için tıklayın"
        >
          <span className="channel-avatar-dot channel-avatar-dot--empty" />
          <span className="channel-switcher-label">Kanal Bağla +</span>
        </Link>
      </div>
    )
  }

  const ribbonColor = activeChannel?.ribbon_color || '#0e9f6e'

  return (
    <div className="channel-switcher" ref={containerRef}>
      <button
        type="button"
        className={`channel-switcher-trigger${isOpen ? ' is-open' : ''}`}
        onClick={() => setIsOpen((prev) => !prev)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label="Aktif kanalı değiştir"
        title="Kanalı / alt hesabı değiştir"
      >
        <div className="channel-switcher-leading">
          <span
            className="channel-avatar-dot"
            style={{ backgroundColor: ribbonColor }}
            aria-hidden="true"
          />
        </div>
        <div className="channel-switcher-text">
          <span className="channel-switcher-name" title={activeChannel?.name ?? 'Kanal Seçin'}>
            {activeChannel?.name ?? 'Kanal Seçin'}
          </span>
          <span className="channel-switcher-sub">
            {activeChannel?.handle ? activeChannel.handle : 'Alt Hesap'}
          </span>
        </div>
        <svg
          className="channel-switcher-chevron"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            d="M6 8L10 12L14 8"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {isOpen && (
        <div className="channel-switcher-dropdown" role="listbox" aria-label="Kanallar">
          <div className="channel-switcher-dropdown-header">
            <span>Alt Hesaplar ({channels.length})</span>
          </div>

          <div className="channel-switcher-list">
            {channels.map((ch) => {
              const isSelected = ch.id === activeChannelId
              const chColor = ch.ribbon_color || '#0e9f6e'
              return (
                <button
                  key={ch.id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  className={`channel-option${isSelected ? ' is-selected' : ''}`}
                  onClick={() => handleSelect(ch)}
                >
                  <span
                    className="channel-option-dot"
                    style={{ backgroundColor: chColor }}
                    aria-hidden="true"
                  />
                  <div className="channel-option-info">
                    <span className="channel-option-name">{ch.name}</span>
                    {ch.handle && (
                      <span className="channel-option-handle">{ch.handle}</span>
                    )}
                  </div>
                  {isSelected && (
                    <span className="channel-option-check" aria-hidden="true">
                      ✓
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          <div className="channel-switcher-footer">
            <Link
              to="/kanallar"
              className="channel-manage-link"
              onClick={() => {
                setIsOpen(false)
                if (onSelect) onSelect()
              }}
            >
              <span>+ Kanal Ekle & Yönet</span>
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

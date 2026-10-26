import type { Channel } from '../api/channels'

/** Ekran başlığında aktif kanalı taşıyan hap: pill--idle malzemesi
    + kanalın kurdele rengi noktası. */
export function ChannelPill({ channel }: { channel: Channel }) {
  return (
    <span className="pill pill--idle channel-pill">
      <span
        className="channel-pill-dot"
        style={{ backgroundColor: channel.ribbon_color || '#0e9f6e' }}
        aria-hidden="true"
      />
      <span className="channel-pill-name">{channel.name}</span>
      {channel.handle && (
        <small className="channel-pill-handle">{channel.handle}</small>
      )}
    </span>
  )
}

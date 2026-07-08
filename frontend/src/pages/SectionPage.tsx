import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'

type SectionPageProps = {
  title: string
  subtitle: string
  description: string
  highlights: string[]
}

export default function SectionPage({ title, subtitle, description, highlights }: SectionPageProps) {
  return (
    <AppShell title={title} subtitle={subtitle}>
      <section className="foundation-card">
        <div>
          <p className="eyebrow">РАЗДЕЛ ПЛАТФОРМЫ</p>
          <h2>{subtitle}</h2>
          <p>{description}</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            {highlights.map((item) => (
              <span key={item}>✓ {item}</span>
            ))}
          </div>
        </div>
      </section>
    </AppShell>
  )
}
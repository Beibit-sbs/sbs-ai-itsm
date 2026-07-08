import { Component, type ErrorInfo, type ReactNode } from 'react'

type AppErrorBoundaryProps = {
  children: ReactNode
}

type AppErrorBoundaryState = {
  hasError: boolean
}

export default class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('UI runtime error:', error, info)
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <main className="dashboard">
          <section className="foundation-card">
            <h2>Ошибка интерфейса</h2>
            <p className="error-message">Не удалось отрисовать страницу. Обновите браузер или выполните повторный вход.</p>
          </section>
        </main>
      )
    }

    return this.props.children
  }
}

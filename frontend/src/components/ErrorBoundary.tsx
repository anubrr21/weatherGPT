import { Component, type ReactNode } from 'react'

interface Props {
  label: string
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="ribbon severe">
        <span>
          {this.props.label} hit a problem: {this.state.error.message}.{' '}
          <button className="link-btn" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </span>
      </div>
    )
  }
}

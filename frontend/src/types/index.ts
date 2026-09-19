import type React from 'react'

// ─── Primitives ──────────────────────────────────────────────────────────────

export type SentimentType = 'positivo' | 'neutro' | 'negativo'

// ─── API Response Interfaces ──────────────────────────────────────────────────

/** POST /api/v1/auth/login */
export interface LoginResponse {
  token: string
  expires_at: string        // ISO 8601 datetime
  company_name: string
}

/** GET /api/v1/batches/{id}/status */
export interface BatchStatus {
  batch_id: string
  status: 'pending' | 'processing' | 'completed' | 'error'
  total_rows: number
  processed_rows: number
  error_rows: number
  uploaded_at: string       // ISO 8601
  completed_at: string | null
}

/** GET /api/v1/batches/{id}/summary */
export interface BatchSummary {
  batch_id: string
  total_feedbacks: number
  sentiment_distribution: {
    positivo: number
    neutro: number
    negativo: number
  }
  sentiment_percentages: {
    positivo: number
    neutro: number
    negativo: number
  }
  urgent_count: number
}

/** Item from GET /api/v1/batches/{id}/feedbacks */
export interface FeedbackItem {
  id: string
  original_text: string
  sentiment: SentimentType
  score: number             // -1.0 to 1.0
  keywords: string[]
  analyzed_at: string       // ISO 8601
}

/** Item from GET /api/v1/batches/{id}/keywords */
export interface KeywordItem {
  word: string
  frequency: number
}

/** Generic paginated response wrapper */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

/** Item from GET /api/v1/batches */
export interface BatchListItem {
  id: string
  filename: string
  status: 'pending' | 'processing' | 'completed' | 'error'
  total_rows: number
  processed_rows: number
  error_rows: number
  uploaded_at: string       // ISO 8601
  completed_at: string | null
  urgent_count: number
}

// ─── Auth Context State ───────────────────────────────────────────────────────

export interface AuthState {
  token: string | null
  companyName: string | null
  expiresAt: Date | null
}

export interface AuthContextValue extends AuthState {
  login: (token: string, expiresAt: string, companyName: string) => void
  logout: () => void
  isAuthenticated: () => boolean
}

// ─── Dashboard Filters ────────────────────────────────────────────────────────

export interface DashboardFilters {
  activeBatchId: string | null
  sentimentFilter: SentimentType | null
  keywordFilter: string | null
}

// ─── Component Props ──────────────────────────────────────────────────────────

export interface EmptyStateProps {
  message: string
  cta?: React.ReactNode
}

export interface BatchRowProps {
  batch: BatchListItem
  onSelect: (batchId: string) => void
}

export interface CSVUploaderProps {
  onUploadComplete: (batchId: string) => void
}

export interface SummaryCardsProps {
  summary: BatchSummary
}

export interface FeedbackListProps {
  batchId: string
  sentimentFilter: SentimentType | null
  keywordFilter: string | null
}

export interface TriagePanelProps {
  batchId: string
}

export interface SentimentChartProps {
  distribution: {
    positivo: number
    neutro: number
    negativo: number
  }
  onSegmentClick: (sentiment: SentimentType | null) => void
}

export interface KeywordCloudProps {
  keywords: KeywordItem[]
  onWordClick: (word: string | null) => void
}

export interface NavbarProps {
  companyName?: string | null
  activeBatchUrgentCount?: number
  onLogout: () => void
}

// ─── Utility & Request Interfaces ─────────────────────────────────────────────

export type BatchStatusType = 'pending' | 'processing' | 'completed' | 'error'

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  company_name: string
}

export interface UploadResponse {
  batch_id: string
  message?: string
}

export interface FileValidationResult {
  valid: boolean
  error?: string
}

export type FormValidationErrors = Record<string, string>


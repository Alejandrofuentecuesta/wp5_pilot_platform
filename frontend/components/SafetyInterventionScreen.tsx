"use client"

interface SafetyInterventionScreenProps {
  redirectUrl: string | null
}

export default function SafetyInterventionScreen({
  redirectUrl,
}: SafetyInterventionScreenProps) {
  const leaveExperiment = () => {
    if (redirectUrl) window.location.href = redirectUrl
  }

  return (
    <main className="min-h-dvh overflow-y-auto bg-bg-page px-4 py-6 sm:py-10">
      <section
        className="mx-auto w-full max-w-xl overflow-hidden rounded-2xl border border-border bg-bg-surface shadow-lg"
        aria-labelledby="safety-title"
      >
        <div className="px-5 py-7 sm:px-8 sm:py-9">
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-accent"
            aria-hidden="true"
          >
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />
              <path d="M12 8v4M12 16h.01" strokeLinecap="round" />
            </svg>
          </div>

          <h1 id="safety-title" className="m-0 text-center text-2xl font-semibold text-primary">
            No estás solo/a
          </h1>
          <p className="mt-4 text-center text-base leading-6 text-secondary">
            Hemos detenido la conversación porque parece que estás pasando por un momento de
            malestar intenso. Tu bienestar es lo más importante ahora.
          </p>

          <div className="mt-6 space-y-3">
            <a
              href="tel:024"
              className="block rounded-xl border border-border bg-bg-page px-5 py-4 text-center transition-colors hover:border-accent"
            >
              <span className="block text-sm text-secondary">Línea de atención a la conducta suicida</span>
              <span className="mt-1 block text-2xl font-bold text-accent">024</span>
              <span className="mt-1 block text-xs text-tertiary">Gratuita, confidencial y disponible las 24 horas</span>
            </a>

            <a
              href="tel:112"
              className="block rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-center transition-colors hover:border-red-400"
            >
              <span className="block text-sm font-medium text-red-900">Si hay peligro inmediato</span>
              <span className="mt-1 block text-2xl font-bold text-red-700">Llama al 112</span>
            </a>
          </div>

          <p className="mt-6 text-sm leading-5 text-secondary">
            Si puedes, habla ahora con una persona de confianza y aléjate de cualquier cosa con la
            que pudieras hacerte daño. También puedes acudir a un servicio sanitario.
          </p>
          <a
            href="https://www.sanidad.gob.es/linea024/"
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-block text-sm font-medium text-accent underline underline-offset-2"
          >
            Información oficial sobre la Línea 024
          </a>

          <div className="mt-7 border-t border-border pt-5 text-center">
            <p className="text-sm text-secondary">
              Tu participación ha quedado registrada y conservarás la compensación.
            </p>
            {redirectUrl && (
              <button
                type="button"
                onClick={leaveExperiment}
                className="mt-4 w-full rounded-lg bg-accent px-5 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90 sm:w-auto"
              >
                Salir del experimento
              </button>
            )}
          </div>
        </div>
      </section>
    </main>
  )
}

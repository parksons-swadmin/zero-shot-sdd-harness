export default function StubPanel({
  title,
  caption,
  children,
  testId,
}: {
  title: string
  caption: string
  children?: React.ReactNode
  testId: string
}) {
  return (
    <div
      className="rounded-lg border border-dashed border-gray-300 bg-gray-100 p-4 opacity-70"
      data-testid={testId}
    >
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-500">{title}</h3>
        <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-500">
          Coming soon
        </span>
      </div>
      {children}
      <p className="mt-1 text-xs text-gray-400">{caption}</p>
    </div>
  )
}

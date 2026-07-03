'use client'

import AnswerPanel from '@/components/AnswerPanel'
import type { MessageOut } from '@/lib/types'

export default function ChatThread({ messages }: { messages: MessageOut[] }) {
  if (!messages || messages.length === 0) return null

  return (
    <div className="max-h-[32rem] space-y-4 overflow-y-auto" data-testid="chat-thread">
      {messages.map(msg =>
        msg.role === 'user' ? (
          <div key={msg.id} className="flex justify-end" data-testid="chat-turn-user">
            <div className="max-w-[85%] rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">
              {msg.content}
            </div>
          </div>
        ) : (
          <div key={msg.id} className="flex justify-start" data-testid="chat-turn-assistant">
            <div className="w-full max-w-[95%]">
              {msg.query_result ? (
                <AnswerPanel result={msg.query_result} />
              ) : (
                <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-800 shadow-sm">
                  {msg.content}
                </div>
              )}
            </div>
          </div>
        ),
      )}
    </div>
  )
}

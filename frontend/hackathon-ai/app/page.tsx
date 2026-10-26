"use client";

import React, { useState } from 'react';
import { ExecutionRequest, StreamEvent, Language, TestCase } from '../types/api';

export default function Page() {
  const [problemDescription, setProblemDescription] = useState<string>('');
  const [language, setLanguage] = useState<Language>('python');
  const [testCases, setTestCases] = useState<TestCase[]>([{ input: '', expected_output: '' }]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);

  const handleAddTestCase = () => {
    setTestCases([...testCases, { input: '', expected_output: '' }]);
  };

  const handleTestCaseChange = (index: number, field: keyof TestCase, value: string) => {
    const newTestCases = [...testCases];
    newTestCases[index][field] = value;
    setTestCases(newTestCases);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setEvents([]);

    const requestBody: ExecutionRequest = {
      problem_description: problemDescription,
      language,
      max_iterations: 20,
      time_limit_seconds: 5,
      test_cases: testCases.filter(tc => tc.input.trim() || tc.expected_output.trim()),
    };

    try {
      const response = await fetch('http://localhost:8000/api/v1/solve', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.body) throw new Error('ReadableStream not supported.');

      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunks = value.split('\n\n').filter(Boolean);
        for (const ev of chunks) {
          if (ev.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(ev.slice(6)) as StreamEvent;
              setEvents((prev) => [...prev, parsed]);
            } catch (err) {
              console.error("Failed to parse chunk:", err, ev);
            }
          }
        }
      }
    } catch (error) {
      console.error('Error:', error);
      setEvents((prev) => [...prev, { event_type: 'error', message: 'Connection error.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white p-8 font-sans">
      <div className="max-w-6xl mx-auto grid grid-cols-1 xl:grid-cols-2 gap-8">
        
        <div className="bg-gray-800 p-6 rounded-lg border border-gray-700 shadow-xl overflow-y-auto max-h-[800px] custom-scrollbar">
          <h2 className="text-3xl font-bold mb-6 text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-300">
            MCTS AI Solver
          </h2>
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-sm font-semibold text-gray-300">Problem Description / Implementation Plan</label>
                <label className="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded cursor-pointer transition-colors flex items-center gap-1 text-cyan-300">
                  📁 Load File (.md / .txt)
                  <input
                    type="file"
                    accept=".md,.txt"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        const reader = new FileReader();
                        reader.onload = (event) => {
                          const text = event.target?.result as string;
                          if (text) setProblemDescription(text);
                        };
                        reader.readAsText(file);
                      }
                    }}
                  />
                </label>
              </div>
              <textarea
                className="w-full h-36 bg-gray-900 text-gray-100 border border-gray-600 rounded-lg p-4 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm resize-none"
                placeholder="Paste problem text or click 'Load File' to import an Implementation Plan (.md)..."
                value={problemDescription}
                onChange={(e) => setProblemDescription(e.target.value)}
                required
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-300 mb-2">Language</label>
              <select
                className="w-full bg-gray-900 text-gray-100 border border-gray-600 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={language}
                onChange={(e) => setLanguage(e.target.value as Language)}
              >
                <option value="python">Python</option>
                <option value="cpp">C++ (GCC)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-300 mb-2 flex justify-between items-center">
                <span>Test Cases</span>
                <button type="button" onClick={handleAddTestCase} className="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded">
                  + Add Test Case
                </button>
              </label>
              <div className="space-y-3">
                {testCases.map((tc, idx) => (
                  <div key={idx} className="flex gap-3 bg-gray-900 p-3 rounded-lg border border-gray-700">
                    <textarea 
                      className="flex-1 bg-transparent border border-gray-700 p-2 rounded text-sm focus:border-blue-500 focus:outline-none resize-none h-16" 
                      placeholder="Input" 
                      value={tc.input} 
                      onChange={(e) => handleTestCaseChange(idx, 'input', e.target.value)} 
                    />
                    <textarea 
                      className="flex-1 bg-transparent border border-gray-700 p-2 rounded text-sm focus:border-blue-500 focus:outline-none resize-none h-16" 
                      placeholder="Expected Output" 
                      value={tc.expected_output} 
                      onChange={(e) => handleTestCaseChange(idx, 'expected_output', e.target.value)} 
                    />
                  </div>
                ))}
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading || !problemDescription.trim()}
              className="mt-4 w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 px-4 rounded-lg transition-colors disabled:opacity-50 flex justify-center items-center gap-2"
            >
              {isLoading ? 'Processing...' : 'Initialize MCTS Loop'}
            </button>
          </form>
        </div>

        <div className="bg-gray-800 p-6 rounded-lg border border-gray-700 shadow-xl flex flex-col h-[800px]">
          <h2 className="text-2xl font-bold mb-6 text-gray-100">Execution Log</h2>
          <div className="flex-1 overflow-y-auto space-y-4 pr-2">
            {events.map((ev, index) => (
              <div key={index} className="p-4 rounded-lg bg-gray-700/50 border border-gray-600">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-blue-300">
                    {ev.event_type.replace('_', ' ')}
                  </span>
                  {ev.iteration && (
                    <span className="text-xs bg-gray-900 px-2 py-1 rounded">Iter: {ev.iteration}</span>
                  )}
                </div>
                <p className="text-sm text-gray-200 mt-2 font-medium">{ev.message}</p>
                {ev.code_snippet && (
                  <pre className="mt-3 p-3 bg-gray-950 rounded border border-gray-800 overflow-x-auto text-xs font-mono text-gray-300">
                    <code>{ev.code_snippet}</code>
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

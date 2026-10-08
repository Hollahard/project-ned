import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ModelProfiles } from '@native/model-profiles.tsx'
import { createModelInspector, type ModelInspection } from '@native/model-inspection-client.ts'
import type { ControlClient } from '@native/control-client.ts'

const client = (): ControlClient => ({ status: vi.fn().mockResolvedValue({ state: 'detached' }), schema: vi.fn(), list: vi.fn().mockResolvedValue({ profiles: [] }), get: vi.fn(), validate: vi.fn(), save: vi.fn(), delete: vi.fn() })
const result: ModelInspection = { schema: 1, model: 'synthetic', status: 'incomplete', format: 'EXL3', declared_architectures: ['LlamaForCausalLM'], declared_bits: 4, observed_tensor_count: 1, observed_shard_count: 1, bytes_read: 256, index_tensor_count: 2, missing_shards: ['model-00002-of-00002.safetensors'], metadata_fingerprint: 'a'.repeat(64), fingerprint_partial: true, fingerprint_scope: 'metadata_files_weight_headers_and_file_sizes', issues: [], issues_truncated: false, runtime_compatible: null, load_certified: false, weights_content_hashed: false, weight_payload_bytes_read: 0 }
const connected = () => waitFor(() => expect(screen.getByRole('button', { name: 'Save profile' }).hasAttribute('disabled')).toBe(false))
const folder = (value: string) => fireEvent.change(screen.getByLabelText('Model folder'), { target: { value } })
afterEach(cleanup)

it('displays partial metadata and every missing shard without mutating saved settings', async () => {
  const control = client(); const inspect = vi.fn().mockResolvedValue(result)
  render(<ModelProfiles client={control} inspector={{ inspect }} />); await connected()
  folder('C:/approved/synthetic')
  const context = (screen.getByLabelText('Context tokens') as HTMLInputElement).value
  fireEvent.click(screen.getByRole('button', { name: 'Inspect metadata' }))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Model files are incomplete' })).toBeTruthy())
  expect(screen.getByText('model-00002-of-00002.safetensors')).toBeTruthy()
  expect(screen.getByText(/Runtime compatibility and VRAM use remain unchecked/)).toBeTruthy()
  expect((screen.getByLabelText('Context tokens') as HTMLInputElement).value).toBe(context)
  expect(control.save).not.toHaveBeenCalled(); expect(control.validate).not.toHaveBeenCalled()
  folder('C:/approved/other')
  expect(screen.queryByRole('region', { name: 'Model metadata inspection' })).toBeNull()
})

it('ignores late inspection results after folder change, reset and unmount', async () => {
  let finish!: (value: ModelInspection) => void
  const inspect = vi.fn().mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const view = render(<ModelProfiles client={client()} inspector={{ inspect }} />); await connected()
  folder('C:/approved/first'); fireEvent.click(screen.getByRole('button', { name: 'Inspect metadata' }))
  folder('C:/approved/second'); await act(async () => finish(result))
  expect(screen.queryByRole('region', { name: 'Model metadata inspection' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Inspect metadata' }))
  fireEvent.click(screen.getByRole('button', { name: 'New profile' })); await act(async () => finish(result))
  expect(screen.queryByRole('region', { name: 'Model metadata inspection' })).toBeNull()
  folder('C:/approved/third'); fireEvent.click(screen.getByRole('button', { name: 'Inspect metadata' }))
  view.unmount(); await act(async () => finish(result))
  expect(screen.queryByRole('region', { name: 'Model metadata inspection' })).toBeNull()
})

it('keeps profiles available when inspection is unconfigured and sanitizes failures', async () => {
  const control = client()
  render(<ModelProfiles client={control} inspector={createModelInspector()} />); await connected()
  folder('C:/unapproved/model'); fireEvent.click(screen.getByRole('button', { name: 'Inspect metadata' }))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('no host-approved model folder'))
  expect(screen.getByRole('button', { name: 'Save profile' }).hasAttribute('disabled')).toBe(false)
})

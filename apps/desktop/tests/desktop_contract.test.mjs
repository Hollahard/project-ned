import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..', '..', '..');

test('Contract schemas exist and are valid JSON', () => {
  const eventsSchema = path.join(projectRoot, 'contracts', 'events.schema.json');
  const apiSchema = path.join(projectRoot, 'contracts', 'api.schema.json');
  const toolSchema = path.join(projectRoot, 'contracts', 'tool.schema.json');

  assert.ok(fs.existsSync(eventsSchema), 'events.schema.json must exist');
  assert.ok(fs.existsSync(apiSchema), 'api.schema.json must exist');
  assert.ok(fs.existsSync(toolSchema), 'tool.schema.json must exist');

  const eventsJson = JSON.parse(fs.readFileSync(eventsSchema, 'utf8'));
  const apiJson = JSON.parse(fs.readFileSync(apiSchema, 'utf8'));
  const toolJson = JSON.parse(fs.readFileSync(toolSchema, 'utf8'));

  assert.equal(eventsJson.title, 'FridayEventEnvelope');
  assert.equal(apiJson.title, 'FridayApiContract');
  assert.equal(toolJson.title, 'FridayToolDefinition');
});

test('Tauri desktop configuration is valid JSON', () => {
  const tauriConf = path.join(projectRoot, 'apps', 'desktop', 'src-tauri', 'tauri.conf.json');
  assert.ok(fs.existsSync(tauriConf), 'tauri.conf.json must exist');

  const config = JSON.parse(fs.readFileSync(tauriConf, 'utf8'));
  assert.equal(config.productName, 'Project Friday');
  assert.equal(config.identifier, 'com.friday.desktop');
});

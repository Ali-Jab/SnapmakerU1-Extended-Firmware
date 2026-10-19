// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-PackageHomePage: https://github.com/paxx12-snapmaker-u1/SnapmakerU1-Extended-Firmware
// SPDX-FileCopyrightText: Copyright (c) 2026 @paxx12

'use strict';

// Pure helpers shared by the Filament Manager: UID and colour normalisation,
// the SpoolLink `card_uids` wire format, filament matching, Spoolman payload
// builders, and the RFID assignment decisions. No DOM and no network, so the
// rules that decide what gets written to Spoolman stay readable in one place.

const MATERIAL_DENSITIES = Object.freeze({
    PLA: 1.24,
    PETG: 1.27,
    ABS: 1.04,
    ASA: 1.07,
    TPU: 1.21,
    NYLON: 1.12,
    PA: 1.12,
    PC: 1.19,
    PVA: 1.19,
    HIPS: 1.04,
    PP: 0.90,
});

function cleanText(value) {
    return value == null ? '' : String(value).trim();
}

function normalizeText(value) {
    return cleanText(value).toLowerCase();
}

function finiteNumber(value) {
    if (value === '' || value == null) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function normalizeUid(value) {
    if (Array.isArray(value) || ArrayBuffer.isView(value)) {
        const bytes = Array.from(value);
        if (bytes.length === 0 || bytes.every(byte => Number(byte) === 0)) return '';
        if (bytes.some(byte => !Number.isInteger(Number(byte)) || Number(byte) < 0 || Number(byte) > 255)) return '';
        return bytes.map(byte => Number(byte).toString(16).padStart(2, '0')).join('').toUpperCase();
    }

    let uid = cleanText(value).replace(/^0x/i, '').replace(/[\s:,.-]/g, '');
    if (!uid || uid.length % 2 !== 0 || !/^[0-9a-f]+$/i.test(uid) || /^0+$/.test(uid)) return '';
    return uid.toUpperCase();
}

function decodeExtraString(value) {
    let decoded = cleanText(value);
    if (decoded.length >= 2 && decoded.startsWith('"') && decoded.endsWith('"')) {
        try {
            const parsed = JSON.parse(decoded);
            if (typeof parsed === 'string') decoded = parsed;
        } catch {
            decoded = decoded.slice(1, -1);
        }
    }
    return decoded;
}

function encodeExtraString(value) {
    return JSON.stringify(cleanText(value));
}

function uniqueUids(values) {
    const seen = new Set();
    const result = [];
    for (const value of values || []) {
        const uid = normalizeUid(value);
        if (uid && !seen.has(uid)) {
            seen.add(uid);
            result.push(uid);
        }
    }
    return result;
}

function parseCardUids(spool) {
    const raw = decodeExtraString(spool?.extra?.card_uids || '');
    return uniqueUids(raw.split(','));
}

function encodeCardUids(values) {
    return encodeExtraString(uniqueUids(values).join(','));
}

function parseVariant(filament) {
    return decodeExtraString(filament?.extra?.variant || '');
}

function canonicalVariant(value) {
    const variant = normalizeText(value);
    return variant === 'basic' ? '' : variant;
}

function normalizeColor(value) {
    const color = cleanText(value).replace(/^#/, '').toUpperCase();
    return /^[0-9A-F]{6}$/.test(color) ? color : '';
}

function materialDensity(material, reportedDensity) {
    const reported = finiteNumber(reportedDensity);
    if (reported != null && reported >= 0.5 && reported <= 3.0) return reported;
    return MATERIAL_DENSITIES[cleanText(material).toUpperCase()] || 1.24;
}

function defaultFilamentName(metadata) {
    const parts = [
        cleanText(metadata?.material),
        cleanText(metadata?.variant),
        normalizeColor(metadata?.color),
    ].filter(Boolean);
    const deduped = parts.filter((part, index) => index === 0 || normalizeText(part) !== normalizeText(parts[index - 1]));
    return deduped.join(' ') || 'Custom Filament';
}

function isCreateEligible(channel) {
    const metadata = channel?.rfid_data || {};
    return !!(
        normalizeUid(channel?.uid) &&
        cleanText(metadata.vendor) &&
        cleanText(metadata.type) &&
        normalizeColor(metadata.color)
    );
}

// Exact vendor/material/variant/colour identity, with blank and `Basic`
// variants treated as equivalent. Returns null when the metadata is too
// incomplete to identify anything, so callers can skip matching entirely.
function metadataKey(metadata) {
    const vendor = normalizeText(metadata?.vendor);
    const material = normalizeText(metadata?.material || metadata?.type);
    const color = normalizeColor(metadata?.color);
    if (!vendor || !material || !color) return null;
    return `${vendor}|${material}|${canonicalVariant(metadata?.variant || metadata?.sub_type)}|${color}`;
}

function filamentKey(filament) {
    return metadataKey({
        vendor: filament?.vendor?.name,
        material: filament?.material,
        variant: parseVariant(filament),
        color: filament?.color_hex,
    });
}

function findMatchingFilaments(filaments, metadata) {
    const key = metadataKey(metadata);
    if (!key) return [];
    return (filaments || []).filter(filament => filamentKey(filament) === key);
}

// Spools whose filament is the same vendor/material/variant/colour as the
// tag, so the picker can suggest them instead of a duplicate spool.
function findMatchingSpools(spools, metadata) {
    const key = metadataKey(metadata);
    if (!key) return [];
    return (spools || []).filter(spool => filamentKey(spool?.filament) === key);
}

function buildFilamentPayload(values, vendorId) {
    const diameter = finiteNumber(values?.diameter);
    const density = finiteNumber(values?.density);
    const color = normalizeColor(values?.color);
    const name = cleanText(values?.name);
    const material = cleanText(values?.material);
    if (!name) throw new Error('Filament name is required');
    if (!material) throw new Error('Material is required');
    if (!color) throw new Error('A valid six-digit colour is required');
    if (diameter == null || diameter <= 0) throw new Error('Diameter must be greater than zero');
    if (density == null || density <= 0) throw new Error('Density must be greater than zero');

    const payload = {
        name,
        material,
        color_hex: color,
        diameter,
        density,
    };
    if (Number.isInteger(Number(vendorId)) && Number(vendorId) > 0) payload.vendor_id = Number(vendorId);

    const weight = finiteNumber(values?.net_weight);
    const tare = finiteNumber(values?.tare_weight);
    const nozzle = finiteNumber(values?.nozzle_temp);
    const bed = finiteNumber(values?.bed_temp);
    if (weight != null && weight > 0) payload.weight = weight;
    if (tare != null && tare >= 0) payload.spool_weight = tare;
    if (nozzle != null && nozzle > 0) payload.settings_extruder_temp = Math.round(nozzle);
    if (bed != null && bed > 0) payload.settings_bed_temp = Math.round(bed);

    const variant = cleanText(values?.variant);
    if (variant) payload.extra = { variant: encodeExtraString(variant) };
    return payload;
}

function buildSpoolPayload(filamentId, values) {
    const id = Number(filamentId);
    const uid = normalizeUid(values?.uid);
    const netWeight = finiteNumber(values?.net_weight);
    const tareWeight = finiteNumber(values?.tare_weight);
    if (!Number.isInteger(id) || id <= 0) throw new Error('A valid filament is required');
    if (!uid) throw new Error('A valid RFID UID is required');
    if (netWeight == null || netWeight <= 0) throw new Error('Net weight must be greater than zero');

    const payload = {
        filament_id: id,
        initial_weight: netWeight,
        remaining_weight: netWeight,
        extra: { card_uids: encodeCardUids([uid]) },
    };
    if (tareWeight != null && tareWeight >= 0) payload.spool_weight = tareWeight;
    return payload;
}

function findUidOwners(spools, uidValue) {
    const uid = normalizeUid(uidValue);
    if (!uid) return [];
    return (spools || []).filter(spool => parseCardUids(spool).includes(uid));
}

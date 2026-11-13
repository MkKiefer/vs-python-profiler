<script setup lang="ts">
import { Cat } from '../../../shared/model';
import { CATEGORY_LABELS, frameColor } from '../../charts/colors';

defineProps<{ summary: string }>();

const CATEGORIES = [Cat.User, Cat.Lib, Cat.Std, Cat.Synth];
</script>

<template>
  <div class="legend bordered-b m-0 px-3.5 py-1">
    <span v-for="cat in CATEGORIES" :key="cat">
      <span class="cat-dot" :style="{ background: frameColor(cat, CATEGORY_LABELS[cat]) }" />{{ CATEGORY_LABELS[cat] }}
    </span>
    <span class="flex-1" />
    <span>{{ summary }}</span>
  </div>
</template>

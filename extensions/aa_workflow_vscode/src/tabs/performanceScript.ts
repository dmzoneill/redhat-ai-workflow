/**
 * Performance Tab webview scripts.
 * Extracted from PerformanceTab.ts to reduce main file size.
 */

import {
  MINDMAP_PHYSICS_DEFAULTS,
  MINDMAP_SLIDER_RANGES,
} from "./performanceConfig";

export function getPerformanceScript(): string {
  const charge = MINDMAP_SLIDER_RANGES.charge;
  const linkDist = MINDMAP_SLIDER_RANGES.linkDist;
  const collision = MINDMAP_SLIDER_RANGES.collision;
  const radial = MINDMAP_SLIDER_RANGES.radial;
  const decay = MINDMAP_SLIDER_RANGES.decay;
  const velocity = MINDMAP_SLIDER_RANGES.velocity;

  return `
      (function() {
        TabEventDelegation.registerClickHandler('performance', function(action, element, e) {
          e.stopPropagation();
          var questionId = element.getAttribute('data-question');
          var dateVal = element.getAttribute('data-date');
          var keyVal = element.getAttribute('data-key');

          if (action === 'logActivity') {
            var category = document.getElementById('activityCategory')?.value;
            var description = document.getElementById('activityDescription')?.value;
            if (description) {
              vscode.postMessage({
                command: 'performanceAction',
                action: 'logActivity',
                category: category,
                description: description
              });
              document.getElementById('activityDescription').value = '';
            }
          } else if (action === 'switchTab') {
            var tabId = keyVal;
            document.querySelectorAll('.meetings-subtab').forEach(function(btn) {
              btn.classList.toggle('active', btn.getAttribute('data-key') === tabId);
            });
            vscode.postMessage({
              command: 'performanceAction',
              action: 'switchTab',
              key: tabId
            });
          } else if (action === 'switchCompView') {
            var viewId = element.getAttribute('data-view') || 'sunburst';
            document.querySelectorAll('.perf-chart-view-btn').forEach(function(btn) {
              btn.classList.toggle('active', btn.getAttribute('data-view') === viewId);
            });
            vscode.postMessage({
              command: 'performanceAction',
              action: 'switchCompView',
              view: viewId
            });
          } else if (action === 'selectDay') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'selectDay',
              date: dateVal
            });
          } else if (action === 'closeDay') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'closeDay'
            });
          } else if (action === 'prevMonth' || action === 'nextMonth') {
            vscode.postMessage({
              command: 'performanceAction',
              action: action
            });
          } else if (action === 'toggleNode') {
            var treeParent = element.closest('.perf-tree-node');
            var cardParent = element.closest('.issue-card');
            if (treeParent) {
              var childrenDiv = treeParent.nextElementSibling;
              if (childrenDiv && childrenDiv.classList.contains('perf-tree-children')) {
                childrenDiv.classList.toggle('collapsed');
                element.classList.toggle('expanded');
              }
            } else if (cardParent) {
              var cardChildren = cardParent.querySelector('.perf-tree-children');
              if (cardChildren) {
                cardChildren.classList.toggle('collapsed');
                element.classList.toggle('expanded');
              }
            }
          } else if (action === 'toggleCompetency') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'toggleCompetency',
              key: keyVal
            });
          } else if (action === 'openIssue') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'openIssue',
              key: keyVal
            });
          } else if (action === 'togglePerfPhysics') {
            var pp = document.getElementById('perfMmPhysicsPanel');
            if (pp) {
              pp.classList.toggle('hidden');
              element.classList.toggle('active', !pp.classList.contains('hidden'));
            }
          } else if (action === 'toggleScoringSettings' || action === 'resetScoringConfig') {
            vscode.postMessage({ command: 'performanceAction', action: action });
          } else if (action === 'toggleScoringComp') {
            vscode.postMessage({ command: 'performanceAction', action: action, key: keyVal });
          } else if (action === 'toggleEventType') {
            vscode.postMessage({
              command: 'performanceAction', action: action,
              comp: element.closest('[data-comp]')?.dataset?.comp || element.dataset.comp,
              value: element.dataset.value
            });
          } else if (action === 'removePhrase' || action === 'removeKeyword') {
            vscode.postMessage({
              command: 'performanceAction', action: action,
              comp: element.dataset.comp, value: element.dataset.value
            });
          } else if (action === 'removeExecutiveSender' || action === 'deleteExecutiveEmail') {
            vscode.postMessage({
              command: 'performanceAction', action: action,
              value: element.dataset.value
            });
          } else if (action === 'addQuestion') {
            var form = document.getElementById('addQuestionForm');
            if (form) {
              form.classList.toggle('visible');
              var inp = document.getElementById('newQuestionText');
              if (inp && form.classList.contains('visible')) inp.focus();
            }
          } else if (action === 'cancelAddQuestion') {
            var form2 = document.getElementById('addQuestionForm');
            if (form2) form2.classList.remove('visible');
            var inp2 = document.getElementById('newQuestionText');
            if (inp2) inp2.value = '';
          } else if (action === 'saveQuestion') {
            var inp3 = document.getElementById('newQuestionText');
            var text = inp3 ? inp3.value.trim() : '';
            if (text) {
              vscode.postMessage({ command: 'performanceAction', action: 'saveQuestion', description: text });
              inp3.value = '';
              var form3 = document.getElementById('addQuestionForm');
              if (form3) form3.classList.remove('visible');
            }
          } else if (action === 'removeQuestion') {
            var qId = element.getAttribute('data-question');
            if (qId) {
              vscode.postMessage({ command: 'performanceAction', action: 'removeQuestion', questionId: qId });
            }
          } else if (action === 'clearDrafts') {
            vscode.postMessage({ command: 'performanceAction', action: 'clearDrafts' });
          } else if (action === 'askAI') {
            var aiInput = document.getElementById('aiAskInput');
            var aiQuestion = aiInput ? aiInput.value.trim() : '';
            if (aiQuestion) {
              vscode.postMessage({ command: 'performanceAction', action: 'askAI', question: aiQuestion });
            }
          } else if (action === 'getGapCoach') {
            var compId = element.getAttribute('data-competency');
            if (compId) {
              vscode.postMessage({ command: 'performanceAction', action: 'getGapCoach', competencyId: compId });
            }
          } else if (action === 'explainScore') {
            var compId2 = element.getAttribute('data-competency');
            if (compId2) {
              vscode.postMessage({ command: 'performanceAction', action: 'explainScore', competencyId: compId2 });
            }
          } else if (action === 'startFilteredBackfill') {
            var git = document.getElementById('bfSrcGit');
            var jira = document.getElementById('bfSrcJira');
            var gitlab = document.getElementById('bfSrcGitlab');
            var github = document.getElementById('bfSrcGithub');
            var gdrive = document.getElementById('bfSrcGdrive');
            var meeting = document.getElementById('bfSrcMeeting');
            var scopeUser = document.getElementById('bfScopeUser');
            var scopePeers = document.getElementById('bfScopePeers');
            var scopeEmails = document.getElementById('bfScopeEmails');
            var drSel = document.getElementById('bfDateRange');
            vscode.postMessage({
              command: 'performanceAction',
              action: 'startFilteredBackfill',
              srcGit: git ? git.checked : true,
              srcJira: jira ? jira.checked : true,
              srcGitlab: gitlab ? gitlab.checked : true,
              srcGithub: github ? github.checked : true,
              srcGdrive: gdrive ? gdrive.checked : true,
              srcMeeting: meeting ? meeting.checked : true,
              scopeUser: scopeUser ? scopeUser.checked : true,
              scopePeers: scopePeers ? scopePeers.checked : true,
              scopeEmails: scopeEmails ? scopeEmails.checked : true,
              dateRange: drSel ? drSel.value : 'full'
            });
          } else {
            var evidenceId = element.getAttribute('data-evidence');
            vscode.postMessage({
              command: 'performanceAction',
              action: action,
              questionId: questionId,
              evidenceId: evidenceId,
              key: keyVal
            });
          }
        });

        // Tag input: Enter key adds a phrase/keyword
        document.addEventListener('keydown', function(e) {
          var input = e.target;
          if (!input || !input.classList || !input.classList.contains('scoring-tag-input')) return;
          if (e.key !== 'Enter') return;
          e.preventDefault();
          var val = input.value.trim();
          if (!val) return;
          var act = input.dataset.action;
          var comp = input.dataset.comp;
          vscode.postMessage({ command: 'performanceAction', action: act, comp: comp, value: val });
          input.value = '';
        });

        // Engineering level selector
        document.addEventListener('change', function(e) {
          var sel = e.target;
          if (!sel || !sel.classList || !sel.classList.contains('scoring-level-select')) return;
          vscode.postMessage({ command: 'performanceAction', action: 'setEngineeringLevel', value: sel.value });
        });

        // Number input changes for globals, base_points, and new scoring fields
        document.addEventListener('change', function(e) {
          var input = e.target;
          if (!input) return;

          // Handle scoring toggle checkboxes
          if (input.type === 'checkbox' && input.dataset && input.dataset.action) {
            vscode.postMessage({
              command: 'performanceAction',
              action: input.dataset.action,
              value: input.checked
            });
            return;
          }

          // Handle select elements with data-action
          if (input.tagName === 'SELECT' && input.dataset && input.dataset.action) {
            vscode.postMessage({
              command: 'performanceAction',
              action: input.dataset.action,
              value: input.value
            });
            return;
          }

          if (!input.classList || !input.classList.contains('scoring-input')) return;

          // New action-based inputs (scope multipliers, role weights, pillar weights, etc.)
          var act = input.dataset.action;
          if (act) {
            var msg = { command: 'performanceAction', action: act, value: input.value };
            if (input.dataset.scope) msg.scope = input.dataset.scope;
            if (input.dataset.role) msg.role = input.dataset.role;
            if (input.dataset.pillar) msg.pillar = input.dataset.pillar;
            vscode.postMessage(msg);
            return;
          }

          var field = input.dataset.field;
          var comp = input.dataset.comp;
          var val = parseInt(input.value, 10);
          if (isNaN(val)) return;
          if (comp) {
            vscode.postMessage({ command: 'performanceAction', action: 'updateCompBasePoints', comp: comp, value: val });
          } else if (field) {
            vscode.postMessage({ command: 'performanceAction', action: 'updateScoringGlobal', field: field, value: val });
          }
        });
      })();

      // ============ QC Mind Map (D3 Force-Directed - Issues + Competencies views) ============
      (function() {
        var perfMmState = {
          simulation: null,
          showLabels: false,
          sticky: false,
          zoom: null,
          svg: null,
          g: null,
          nodeSelection: null,
          linkSelection: null,
          allLinks: null,
          glowG: null,
          pillarNodes: null,
          chargeStrength: ${MINDMAP_PHYSICS_DEFAULTS.chargeStrength},
          linkDistance: ${MINDMAP_PHYSICS_DEFAULTS.linkDistance},
          collisionRadius: ${MINDMAP_PHYSICS_DEFAULTS.collisionRadius},
          radialScale: ${MINDMAP_PHYSICS_DEFAULTS.radialScale},
          alphaDecay: ${MINDMAP_PHYSICS_DEFAULTS.alphaDecay},
          velocityDecay: ${MINDMAP_PHYSICS_DEFAULTS.velocityDecay},
          paused: false
        };

        function escapeHtml(s) {
          if (!s) return '';
          return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function fitPerfMindmap(svg, g, zoomBehavior, width, height) {
          if (!g || !g.node()) return;
          var bounds = g.node().getBBox();
          if (!bounds.width || !bounds.height) return;
          var scale = 0.85 / Math.max(bounds.width / width, bounds.height / height);
          scale = Math.min(Math.max(scale, 0.15), 3);
          var tx = width / 2 - scale * (bounds.x + bounds.width / 2);
          var ty = height / 2 - scale * (bounds.y + bounds.height / 2);
          svg.transition().duration(750)
            .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
        }

        function togglePerfMmLabels(g) {
          var existing = g.selectAll('.perf-mm-opt-label');
          if (perfMmState.showLabels) {
            if (existing.empty()) {
              g.selectAll('.perf-mm-node').each(function(d) {
                if (d.type === 'root') return;
                d3.select(this).append('text')
                  .attr('class', 'perf-mm-opt-label')
                  .attr('dy', (d.size || 8) + 12)
                  .attr('text-anchor', 'middle')
                  .attr('fill', 'var(--vscode-foreground, #ccc)')
                  .attr('font-size', d.type === 'pillar' || d.type === 'strategy' ? '11px' : '9px')
                  .text(function(dd) {
                    var t = dd.fullLabel || dd.fullKey || dd.label;
                    return t.length > 22 ? t.substring(0, 19) + '...' : t;
                  });
              });
            } else { existing.style('display', null); }
          } else { existing.style('display', 'none'); }
        }

        function applyFilters() {
          // Gather visible pillars
          var visiblePillars = new Set();
          document.querySelectorAll('.perfMmPillarChk').forEach(function(chk) {
            if (chk.checked) visiblePillars.add(chk.dataset.pillar);
          });

          // Gather visible node types from checkboxes
          var checkedTypes = new Set();
          document.querySelectorAll('.perfMmTypeChk').forEach(function(chk) {
            if (chk.checked) {
              chk.dataset.types.split(',').forEach(function(t) { checkedTypes.add(t); });
            }
          });

          // Cascade: if ANSTRATs hidden -> epics hidden -> issues hidden
          var showAnstrat = checkedTypes.has('anstrat');
          var showEpic = checkedTypes.has('epic');
          var showIssue = checkedTypes.has('task') || checkedTypes.has('bug') || checkedTypes.has('story');

          var visibleTypes = new Set();
          visibleTypes.add('root');
          visibleTypes.add('pillar');
          if (checkedTypes.has('competency')) visibleTypes.add('competency');
          if (checkedTypes.has('strategy')) visibleTypes.add('strategy');
          if (checkedTypes.has('owner')) visibleTypes.add('owner');
          if (showAnstrat) visibleTypes.add('anstrat');
          if (showAnstrat && showEpic) visibleTypes.add('epic');
          if (showAnstrat && showEpic && showIssue) {
            visibleTypes.add('task');
            visibleTypes.add('bug');
            visibleTypes.add('story');
          }

          if (!perfMmState.nodeSelection || !perfMmState.linkSelection) return;

          // Build a map of hidden node IDs for parent-cascade on unattached nodes
          var hiddenParents = new Set();

          perfMmState.nodeSelection.each(function(d) {
            var visible = true;
            if (d.type === 'root') { visible = true; }
            else if (d.type === 'pillar') {
              visible = visiblePillars.has(d.id);
            } else if (d.type === 'owner') {
              visible = visibleTypes.has('owner');
            } else {
              var typeOk = visibleTypes.has(d.type);
              var pillarOk = true;
              if (d.pillars && d.pillars.length > 0) {
                pillarOk = d.pillars.some(function(p) { return visiblePillars.has(p); });
              }
              visible = typeOk && pillarOk;
            }
            d._visible = visible;
            if (!visible) hiddenParents.add(d.id);
            d3.select(this)
              .style('opacity', visible ? 1 : 0.06)
              .style('pointer-events', visible ? 'auto' : 'none');
          });

          perfMmState.linkSelection.each(function(d) {
            var src = typeof d.source === 'object' ? d.source : null;
            var tgt = typeof d.target === 'object' ? d.target : null;
            var visible = (!src || src._visible !== false) && (!tgt || tgt._visible !== false);
            d3.select(this).style('opacity', visible ? 1 : 0.03);
          });

          // Fade heat glows for hidden pillars
          if (perfMmState.glowG && perfMmState.pillarNodes) {
            perfMmState.pillarNodes.forEach(function(p, i) {
              var pct = Math.max(0, Math.min(100, p.percentage || 0));
              var vis = visiblePillars.has(p.id);
              d3.select(perfMmState.glowG.selectAll('.perf-mm-heat-glow').nodes()[i])
                .attr('opacity', vis ? (0.02 + (pct / 100) * 0.10) : 0);
            });
          }
        }

        function setupControls(container) {
          var labelsChk = document.getElementById('perfMmLabels');
          if (labelsChk) {
            labelsChk.checked = perfMmState.showLabels;
            labelsChk.addEventListener('change', function() {
              perfMmState.showLabels = this.checked;
              if (perfMmState.g) togglePerfMmLabels(perfMmState.g);
            });
          }
          var stickyChk = document.getElementById('perfMmSticky');
          if (stickyChk) {
            stickyChk.checked = perfMmState.sticky;
            stickyChk.addEventListener('change', function() { perfMmState.sticky = this.checked; });
          }
          var reheatBtn = document.getElementById('perfMmReheat');
          if (reheatBtn) {
            reheatBtn.addEventListener('click', function() {
              if (perfMmState.simulation) {
                perfMmState.simulation.nodes().forEach(function(d) { d.fx = null; d.fy = null; });
                perfMmState.simulation.alpha(1).restart();
              }
            });
          }
          var fitBtn = document.getElementById('perfMmFit');
          if (fitBtn) {
            fitBtn.addEventListener('click', function() {
              fitPerfMindmap(perfMmState.svg, perfMmState.g, perfMmState.zoom,
                container.clientWidth || 800, container.clientHeight || 600);
            });
          }

          // Pillar filter checkboxes
          document.querySelectorAll('.perfMmPillarChk').forEach(function(chk) {
            chk.addEventListener('change', applyFilters);
          });

          // Node type filter checkboxes
          document.querySelectorAll('.perfMmTypeChk').forEach(function(chk) {
            chk.addEventListener('change', applyFilters);
          });

          // Physics panel toggle - use document-level listener to survive DOM updates
          if (!window._perfPhysicsToggleAttached) {
            window._perfPhysicsToggleAttached = true;
            document.addEventListener('click', function(e) {
              var btn = e.target.closest && e.target.closest('#perfMmPhysicsToggle');
              if (!btn) return;
              var pp = document.getElementById('perfMmPhysicsPanel');
              if (!pp) return;
              e.preventDefault();
              e.stopPropagation();
              pp.classList.toggle('hidden');
              btn.classList.toggle('active', !pp.classList.contains('hidden'));
            }, true);
          }

          // Helper: setup a physics slider
          function perfMmSetupSlider(sliderId, valueId, onUpdate, formatFn) {
            var slider = document.getElementById(sliderId);
            var valueEl = document.getElementById(valueId);
            if (slider) {
              slider.addEventListener('input', function() {
                var v = parseFloat(this.value);
                if (valueEl) valueEl.textContent = formatFn(v);
                onUpdate(v);
              });
            }
          }

          function perfMmSetSlider(sliderId, valueId, sliderVal, displayVal) {
            var s = document.getElementById(sliderId);
            var v = document.getElementById(valueId);
            if (s) s.value = sliderVal;
            if (v) v.textContent = displayVal;
          }

          function perfMmUpdateForce(forceName, updateFn) {
            if (perfMmState.simulation && perfMmState.simulation.force(forceName)) {
              updateFn(perfMmState.simulation);
              perfMmState.simulation.alpha(0.3).restart();
            }
          }

          // Repulsion slider
          perfMmSetupSlider('perfMmChargeSlider', 'perfMmChargeValue', function(v) {
            perfMmState.chargeStrength = v;
            perfMmUpdateForce('charge', function(sim) {
              var ratio = v / ${MINDMAP_PHYSICS_DEFAULTS.chargeStrength};
              sim.force('charge').strength(function(d) {
                if (d.type === 'root') return -600 * ratio;
                if (d.type === 'pillar') return -350 * ratio;
                if (d.type === 'competency') return -100 * ratio;
                if (d.type === 'anstrat') return -180 * ratio;
                if (d.type === 'owner') return -200 * ratio;
                if (d.type === 'epic') return -80 * ratio;
                if (d.type === 'strategy') return -60 * ratio;
                return -30 * ratio;
              });
            });
          }, function(v) { return String(v); });

          // Link distance slider
          perfMmSetupSlider('perfMmLinkDistSlider', 'perfMmLinkDistValue', function(v) {
            perfMmState.linkDistance = v;
            perfMmUpdateForce('link', function(sim) {
              var ratio = v / ${MINDMAP_PHYSICS_DEFAULTS.linkDistance};
              sim.force('link').distance(function(d) {
                if (d.type === 'evidence') return 250 * ratio;
                if (d.type === 'comp_anstrat') return 120 * ratio;
                if (d.type === 'anstrat_strategy') return 140 * ratio;
                if (d.type === 'owner_anstrat') return 100 * ratio;
                if (d.type === 'pillar_strategy') return 160 * ratio;
                var src = typeof d.source === 'object' ? d.source : null;
                var tgt = typeof d.target === 'object' ? d.target : null;
                if (src && src.type === 'root') return 160 * ratio;
                if (src && src.type === 'pillar' && tgt && tgt.type === 'competency') return 140 * ratio;
                if (src && src.type === 'anstrat') return 70 * ratio;
                if (tgt && (tgt.type === 'task' || tgt.type === 'bug' || tgt.type === 'story')) return 45 * ratio;
                return 90 * ratio;
              });
            });
          }, function(v) { return String(v); });

          // Collision padding slider
          perfMmSetupSlider('perfMmCollisionSlider', 'perfMmCollisionValue', function(v) {
            perfMmState.collisionRadius = v;
            perfMmUpdateForce('collision', function(sim) {
              sim.force('collision').radius(function(d) { return (d.size || 8) + v; });
            });
          }, function(v) { return String(v); });

          // Radial spread slider
          perfMmSetupSlider('perfMmRadialSlider', 'perfMmRadialValue', function(v) {
            var scale = v / 100;
            perfMmState.radialScale = scale;
            if (perfMmState.simulation) {
              var sim = perfMmState.simulation;
              var cx2 = (container.clientWidth || 800) / 2;
              var cy2 = (container.clientHeight || 600) / 2;
              sim.force('radial_pillar', d3.forceRadial(220 * scale, cx2, cy2).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }));
              sim.force('radial_comp', d3.forceRadial(360 * scale, cx2, cy2).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }));
              sim.force('radial_anstrat', d3.forceRadial(220 * scale, cx2, cy2).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }));
              sim.force('radial_strat', d3.forceRadial(450 * scale, cx2, cy2).strength(function(d) { return d.type === 'strategy' ? 0.3 : 0; }));
              sim.alpha(0.3).restart();
            }
          }, function(v) { return (v / 100).toFixed(1); });

          // Cooling slider
          perfMmSetupSlider('perfMmDecaySlider', 'perfMmDecayValue', function(v) {
            var mapped = v / 1000;
            perfMmState.alphaDecay = mapped;
            if (perfMmState.simulation) perfMmState.simulation.alphaDecay(mapped);
          }, function(v) { return (v / 1000).toFixed(3); });

          // Friction slider
          perfMmSetupSlider('perfMmVelocitySlider', 'perfMmVelocityValue', function(v) {
            var mapped = v / 100;
            perfMmState.velocityDecay = mapped;
            if (perfMmState.simulation) perfMmState.simulation.velocityDecay(mapped);
          }, function(v) { return (v / 100).toFixed(2); });

          // Reset button
          var physResetBtn = document.getElementById('perfMmPhysicsReset');
          if (physResetBtn) {
            physResetBtn.addEventListener('click', function() {
              perfMmState.chargeStrength = ${MINDMAP_PHYSICS_DEFAULTS.chargeStrength};
              perfMmState.linkDistance = ${MINDMAP_PHYSICS_DEFAULTS.linkDistance};
              perfMmState.collisionRadius = ${MINDMAP_PHYSICS_DEFAULTS.collisionRadius};
              perfMmState.radialScale = ${MINDMAP_PHYSICS_DEFAULTS.radialScale};
              perfMmState.alphaDecay = ${MINDMAP_PHYSICS_DEFAULTS.alphaDecay};
              perfMmState.velocityDecay = ${MINDMAP_PHYSICS_DEFAULTS.velocityDecay};
              perfMmSetSlider('perfMmChargeSlider', 'perfMmChargeValue', '${charge.initial}', '${charge.initial}');
              perfMmSetSlider('perfMmLinkDistSlider', 'perfMmLinkDistValue', '${linkDist.initial}', '${linkDist.initial}');
              perfMmSetSlider('perfMmCollisionSlider', 'perfMmCollisionValue', '${collision.initial}', '${collision.initial}');
              perfMmSetSlider('perfMmRadialSlider', 'perfMmRadialValue', '${radial.initial}', '${(radial.initial / 100).toFixed(1)}');
              perfMmSetSlider('perfMmDecaySlider', 'perfMmDecayValue', '${decay.initial}', '${(decay.initial / 1000).toFixed(3)}');
              perfMmSetSlider('perfMmVelocitySlider', 'perfMmVelocityValue', '${velocity.initial}', '${(velocity.initial / 100).toFixed(2)}');
              if (perfMmState.simulation) {
                perfMmState.simulation.alphaDecay(${MINDMAP_PHYSICS_DEFAULTS.alphaDecay}).velocityDecay(${MINDMAP_PHYSICS_DEFAULTS.velocityDecay}).alpha(0.5).restart();
              }
            });
          }

          // Pause button
          var physPauseBtn = document.getElementById('perfMmPhysicsPause');
          if (physPauseBtn) {
            physPauseBtn.addEventListener('click', function() {
              if (perfMmState.simulation) {
                if (perfMmState.paused) {
                  perfMmState.simulation.alpha(0.3).restart();
                  physPauseBtn.textContent = 'Pause';
                } else {
                  perfMmState.simulation.stop();
                  physPauseBtn.textContent = 'Resume';
                }
                perfMmState.paused = !perfMmState.paused;
              }
            });
          }

          // Unstick All button
          var physUnstickBtn = document.getElementById('perfMmPhysicsUnstick');
          if (physUnstickBtn) {
            physUnstickBtn.addEventListener('click', function() {
              if (perfMmState.simulation) {
                perfMmState.simulation.nodes().forEach(function(d) { d.fx = null; d.fy = null; });
                perfMmState.simulation.alpha(0.3).restart();
              }
            });
          }
        }

        function makeDrag(simulation) {
          return d3.drag()
            .on('start', function(event, d) {
              if (!event.active) simulation.alphaTarget(0.3).restart();
              d.fx = d.x; d.fy = d.y;
            })
            .on('drag', function(event, d) { d.fx = event.x; d.fy = event.y; })
            .on('end', function(event, d) {
              if (!event.active) simulation.alphaTarget(0);
              if (!perfMmState.sticky) { d.fx = null; d.fy = null; }
            });
        }

        function setupTooltipAndHighlight(node, link, links, tooltip) {
          node.on('mouseenter', function(event, d) {
            if (!tooltip) return;
            var html = '';
            if (d.type === 'competency') {
              html = '<strong>' + escapeHtml(d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">' + escapeHtml(d.category || 'Competency') + '</span>';
              html += '<div class="perf-mm-tt-meta">' + d.percentage + '% &middot; ' + d.points + '/' + d.target + ' pts &middot; ' + d.evidenceCount + ' evidence</div>';
              if (d.goal) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.goal) + '</div>';
            } else if (d.type === 'strategy') {
              html = '<strong>' + escapeHtml(d.fullLabel || d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">' + (d.status === 'covered' ? 'Covered' : 'Gap') + '</span>';
              if (d.context) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.context.substring(0, 150)) + '</div>';
              if (d.matchedIssues && d.matchedIssues.length) html += '<div class="perf-mm-tt-meta">' + d.matchedIssues.length + ' matched issues</div>';
              if (d.matchedMrs && d.matchedMrs.length) html += '<div class="perf-mm-tt-meta">' + d.matchedMrs.length + ' matched MRs</div>';
            } else if (d.type === 'pillar') {
              html = '<strong>' + escapeHtml(d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.heatColor + '">' + d.percentage + '%</span>';
              html += '<div class="perf-mm-tt-meta">' + d.compCount + ' competencies &middot; ' + d.priorityCount + ' priorities &middot; ' + d.covered + ' covered &middot; ' + d.gaps + ' gaps</div>';
            } else if (d.type === 'anstrat') {
              html = '<strong>' + escapeHtml(d.fullKey || d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">ANSTRAT</span>';
              if (d.summary) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.summary.substring(0, 150)) + '</div>';
              if (d.points) html += '<div class="perf-mm-tt-meta">' + d.points + ' pts</div>';
              if (d.eventCount) html += '<div class="perf-mm-tt-meta">' + d.eventCount + ' events</div>';
            } else if (d.type === 'owner') {
              html = '<strong>' + escapeHtml(d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type perf-mm-legend-owner">Owner</span>';
              if (d.email) html += '<div class="perf-mm-tt-meta">' + escapeHtml(d.email) + '</div>';
              html += '<div class="perf-mm-tt-meta">' + d.issueCount + ' ANSTRAT issues &middot; ' + d.linkedCount + ' linked</div>';
              if (d.themes && d.themes.length) html += '<div class="perf-mm-tt-summary">Themes: ' + d.themes.map(escapeHtml).join(', ') + '</div>';
            } else {
              var typeLabels = { root: 'Quarter', strategy: 'Strategy', epic: 'Epic', story: 'Story', bug: 'Bug', task: 'Task', group: 'Group', anstrat: 'ANSTRAT' };
              html = '<strong>' + escapeHtml(d.fullKey || d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">' + (typeLabels[d.type] || d.type) + '</span>';
              if (d.summary) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.summary.substring(0, 120)) + '</div>';
              if (d.points) html += '<div class="perf-mm-tt-meta">' + d.points + ' pts</div>';
              if (d.eventCount) html += '<div class="perf-mm-tt-meta">' + d.eventCount + ' events</div>';
            }
            tooltip.innerHTML = html;
            tooltip.style.display = 'block';
            var connectedIds = new Set([d.id]);
            links.forEach(function(l) {
              var sid = l.source.id || l.source;
              var tid = l.target.id || l.target;
              if (sid === d.id) connectedIds.add(tid);
              if (tid === d.id) connectedIds.add(sid);
            });
            node.classed('perf-mm-dimmed', function(n) { return !connectedIds.has(n.id); });
            link.classed('perf-mm-dimmed', function(l) {
              var sid = l.source.id || l.source;
              var tid = l.target.id || l.target;
              return sid !== d.id && tid !== d.id;
            });
          })
          .on('mousemove', function(event) {
            if (!tooltip) return;
            var ctr = document.getElementById('perfMindmapGraph');
            if (!ctr) return;
            var rect = ctr.getBoundingClientRect();
            tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
            tooltip.style.top = (event.clientY - rect.top - 10) + 'px';
          })
          .on('mouseleave', function() {
            if (tooltip) tooltip.style.display = 'none';
            node.classed('perf-mm-dimmed', false);
            link.classed('perf-mm-dimmed', false);
          })
          .on('click', function(event, d) {
            if (d.fullKey && d.fullKey.startsWith('AAP-')) {
              vscode.postMessage({ command: 'performanceAction', action: 'openIssue', key: d.fullKey });
            }
          });
        }

        // ---- Combined unified view ----
        function renderCombinedView(graphData, svg, g, container, width, height) {
          var nodes = graphData.nodes.map(function(d) { return Object.assign({}, d); });
          var links = graphData.links.map(function(d) { return Object.assign({}, d); });

          var cx = width / 2, cy = height / 2;

          // Pre-position nodes radially by type
          var anstratIdx = 0;
          var anstratTotal = nodes.filter(function(d) { return d.type === 'anstrat'; }).length;
          nodes.forEach(function(d) {
            if (d.type === 'root') { d.x = cx; d.y = cy; }
            else if (d.type === 'pillar') {
              var rad = (d.angle || 0) * Math.PI / 180 - Math.PI / 2;
              d.x = cx + 220 * Math.cos(rad);
              d.y = cy + 220 * Math.sin(rad);
            } else if (d.type === 'competency') {
              var pRad = (d.pillarAngle || 0) * Math.PI / 180 - Math.PI / 2;
              var spread = (Math.random() - 0.5) * 0.5;
              d.x = cx + 360 * Math.cos(pRad + spread);
              d.y = cy + 360 * Math.sin(pRad + spread);
            } else if (d.type === 'anstrat') {
              var aRad = (anstratIdx / Math.max(anstratTotal, 1)) * Math.PI * 2 - Math.PI / 2;
              d.x = cx + 220 * Math.cos(aRad);
              d.y = cy + 220 * Math.sin(aRad);
              anstratIdx++;
            } else if (d.type === 'epic') {
              d.x = cx + (Math.random() - 0.5) * 600;
              d.y = cy + (Math.random() - 0.5) * 600;
            } else if (d.type === 'strategy') {
              var sAngle = Math.random() * Math.PI * 2;
              d.x = cx + 450 * Math.cos(sAngle);
              d.y = cy + 450 * Math.sin(sAngle);
            } else {
              d.x = cx + (Math.random() - 0.5) * 800;
              d.y = cy + (Math.random() - 0.5) * 800;
            }
          });

          // Pillar heat glow backgrounds – radius and opacity scale with competency %
          var pillarNodes = nodes.filter(function(d) { return d.type === 'pillar'; });
          var glowG = g.append('g').attr('class', 'perf-mm-heat-glows');
          pillarNodes.forEach(function(p) {
            var pct = Math.max(0, Math.min(100, p.percentage || 0));
            var glowR = 60 + (pct / 100) * 220;
            var glowOpacity = 0.02 + (pct / 100) * 0.10;
            glowG.append('circle')
              .attr('class', 'perf-mm-heat-glow')
              .attr('cx', p.x).attr('cy', p.y).attr('r', glowR)
              .attr('fill', p.color || '#555')
              .attr('opacity', glowOpacity)
              .attr('filter', 'url(#perfHeatGlow)');
          });

          var simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(function(d) { return d.id; })
              .distance(function(d) {
                if (d.type === 'evidence') return 250;
                if (d.type === 'comp_anstrat') return 120;
                if (d.type === 'anstrat_strategy') return 140;
                if (d.type === 'owner_anstrat') return 100;
                if (d.type === 'pillar_strategy') return 160;
                var src = typeof d.source === 'object' ? d.source : null;
                var tgt = typeof d.target === 'object' ? d.target : null;
                if (src && src.type === 'root') return 220;
                if (src && src.type === 'pillar' && tgt && tgt.type === 'competency') return 160;
                if (src && src.type === 'anstrat') return 70;
                if (tgt && (tgt.type === 'task' || tgt.type === 'bug' || tgt.type === 'story')) return 45;
                return 90;
              })
              .strength(function(d) {
                if (d.type === 'evidence') return 0.1;
                if (d.type === 'comp_anstrat') return 0.4;
                if (d.type === 'anstrat_strategy') return 0.35;
                if (d.type === 'owner_anstrat') return 0.5;
                if (d.type === 'pillar_strategy') return 0.35;
                return 0.45;
              }))
            .force('charge', d3.forceManyBody().strength(function(d) {
              if (d.type === 'root') return -800;
              if (d.type === 'pillar') return -600;
              if (d.type === 'competency') return -120;
              if (d.type === 'anstrat') return -180;
              if (d.type === 'owner') return -200;
              if (d.type === 'epic') return -80;
              if (d.type === 'strategy') return -60;
              return -30;
            }))
            .force('radial_pillar', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }))
            .force('radial_comp', d3.forceRadial(360, cx, cy).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }))
            .force('radial_anstrat', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }))
            .force('radial_owner', d3.forceRadial(180, cx, cy).strength(function(d) { return d.type === 'owner' ? 0.2 : 0; }))
            .force('radial_strat', d3.forceRadial(450, cx, cy).strength(function(d) { return d.type === 'strategy' ? 0.3 : 0; }))
            .force('center_root', d3.forceRadial(0, cx, cy).strength(function(d) { return d.type === 'root' ? 1 : 0; }))
            .force('collision', d3.forceCollide().radius(function(d) {
              if (d.type === 'pillar') return (d.size || 22) + 40;
              return (d.size || 8) + 4;
            }))
            .alphaDecay(0.012).velocityDecay(0.35);

          simulation.force('angular_pin', function(alpha) {
            var strength = 0.15 * alpha;
            nodes.forEach(function(d) {
              if (d.type !== 'pillar' || d.angle == null) return;
              var targetRad = d.angle * Math.PI / 180 - Math.PI / 2;
              var tx = cx + 220 * Math.cos(targetRad);
              var ty = cy + 220 * Math.sin(targetRad);
              d.vx += (tx - d.x) * strength;
              d.vy += (ty - d.y) * strength;
            });
          });
          perfMmState.simulation = simulation;

          // Draw links
          var link = g.append('g').attr('class', 'perf-mm-links').selectAll('line').data(links).enter().append('line')
            .attr('class', function(d) {
              if (d.type === 'evidence') return 'perf-mm-link perf-mm-link--evidence';
              if (d.type === 'comp_anstrat') return 'perf-mm-link perf-mm-link--comp-anstrat';
              if (d.type === 'anstrat_strategy') return 'perf-mm-link perf-mm-link--anstrat-strategy';
              if (d.type === 'owner_anstrat') return 'perf-mm-link perf-mm-link--owner-anstrat';
              if (d.type === 'pillar_strategy') return 'perf-mm-link perf-mm-link--pillar-strategy';
              return 'perf-mm-link';
            })
            .attr('stroke', function(d) {
              var src = typeof d.source === 'object' ? d.source : null;
              if (d.type === 'evidence') return src ? (src.color || '#8b5cf6') : '#8b5cf6';
              if (d.type === 'comp_anstrat') return src ? (src.color || '#10b981') : '#10b981';
              if (d.type === 'anstrat_strategy') {
                return src ? (src.color || '#f59e0b') : '#f59e0b';
              }
              if (d.type === 'owner_anstrat') return '#e0e0e0';
              if (d.type === 'pillar_strategy') return src ? (src.color || '#888') : '#888';
              return src ? (src.color || '#555') : '#555';
            })
            .attr('stroke-opacity', function(d) {
              if (d.type === 'evidence') return 0.4;
              if (d.type === 'comp_anstrat') return 0.7;
              if (d.type === 'anstrat_strategy') return 0.7;
              if (d.type === 'owner_anstrat') return 0.6;
              if (d.type === 'pillar_strategy') return 0.55;
              return 0.3;
            })
            .attr('stroke-width', function(d) {
              if (d.type === 'evidence') return Math.min((d.weight || 1) * 1.2, 4);
              if (d.type === 'comp_anstrat') return Math.min((d.weight || 1) + 1.5, 4);
              if (d.type === 'anstrat_strategy') return Math.min((d.weight || 1) + 1.5, 4);
              if (d.type === 'owner_anstrat') return 2;
              if (d.type === 'pillar_strategy') return 2.5;
              var src = typeof d.source === 'object' ? d.source : null;
              if (src && src.type === 'root') return 3;
              if (src && src.type === 'pillar') return 2;
              if (src && src.type === 'anstrat') return 1.8;
              return 1;
            })
            .attr('stroke-dasharray', function(d) {
              if (d.type === 'evidence') return '6,4';
              if (d.type === 'owner_anstrat') return '4,3';
              if (d.type === 'pillar_strategy') return '6,3,2,3';
              return 'none';
            });

          // Draw nodes
          var node = g.append('g').attr('class', 'perf-mm-nodes').selectAll('g').data(nodes).enter().append('g')
            .attr('class', function(d) { return 'perf-mm-node perf-mm-node--' + d.type; })
            .call(makeDrag(simulation));

          // Root glow
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('class', 'perf-mm-glow')
            .attr('r', function(d) { return (d.size || 30) + 6; })
            .attr('fill', 'none').attr('stroke', '#667eea').attr('stroke-width', 2).attr('stroke-opacity', 0.3);

          // Root circle
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('class', 'perf-mm-circle')
            .attr('r', function(d) { return d.size || 30; })
            .attr('fill', '#667eea').attr('stroke', '#8b9cf5').attr('stroke-width', 3);

          // Pillar ring nodes -- always use the pillar's own color, not heat color
          node.filter(function(d) { return d.type === 'pillar'; })
            .append('circle').attr('class', 'perf-mm-ring')
            .attr('r', function(d) { return d.size || 22; })
            .attr('fill', 'none')
            .attr('stroke', function(d) { return d.color; })
            .attr('stroke-width', 3).attr('stroke-opacity', 0.7);

          // Competency circles (heat colored)
          node.filter(function(d) { return d.type === 'competency'; })
            .append('circle').attr('class', 'perf-mm-circle')
            .attr('r', function(d) { return d.size || 10; })
            .attr('fill', function(d) { return d.heatColor || d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.heatColor || d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5);

          // ANSTRAT nodes -- rounded rectangles via rect
          node.filter(function(d) { return d.type === 'anstrat'; })
            .append('rect').attr('class', 'perf-mm-anstrat-rect')
            .attr('width', function(d) { return (d.size || 16) * 4; })
            .attr('height', function(d) { return (d.size || 16) * 2.8; })
            .attr('x', function(d) { return -(d.size || 16) * 2; })
            .attr('y', function(d) { return -(d.size || 16) * 1.4; })
            .attr('rx', 5).attr('ry', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5).attr('opacity', 0.9);

          // Epic triangles (pointing up)
          node.filter(function(d) { return d.type === 'epic'; })
            .append('polygon').attr('class', 'perf-mm-triangle')
            .attr('points', function(d) {
              var s = d.size || 10;
              return '0,' + (-s) + ' ' + (s * 0.9) + ',' + (s * 0.7) + ' ' + (-s * 0.9) + ',' + (s * 0.7);
            })
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1);

          // Issue squares (task/bug/story)
          node.filter(function(d) { return d.type === 'task' || d.type === 'bug' || d.type === 'story'; })
            .append('rect').attr('class', 'perf-mm-issue-rect')
            .attr('width', function(d) { var s = d.size || 6; return s * 1.6; })
            .attr('height', function(d) { var s = d.size || 6; return s * 1.6; })
            .attr('x', function(d) { var s = d.size || 6; return -s * 0.8; })
            .attr('y', function(d) { var s = d.size || 6; return -s * 0.8; })
            .attr('rx', 2).attr('ry', 2)
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('fill-opacity', 0.7)
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.3).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 0.8);

          // Strategy diamonds -- covered=solid bright, gap=dashed dimmer
          node.filter(function(d) { return d.type === 'strategy'; })
            .append('polygon').attr('class', 'perf-mm-diamond')
            .attr('points', function(d) {
              var s = d.size || 12;
              return '0,' + (-s) + ' ' + s + ',0 0,' + s + ' ' + (-s) + ',0';
            })
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', function(d) { return d.isCovered ? 1.5 : 2; })
            .attr('stroke-dasharray', function(d) { return d.isCovered ? 'none' : '4,2'; })
            .attr('opacity', function(d) { return d.isCovered ? 0.9 : 0.65; });

          // Owner hexagons
          node.filter(function(d) { return d.type === 'owner'; })
            .append('polygon').attr('class', 'perf-mm-hexagon')
            .attr('points', function(d) {
              var s = d.size || 18;
              var pts = [];
              for (var i = 0; i < 6; i++) {
                var angle = (Math.PI / 3) * i - Math.PI / 6;
                pts.push(Math.cos(angle) * s + ',' + Math.sin(angle) * s);
              }
              return pts.join(' ');
            })
            .attr('fill', function(d) { return d.color; })
            .attr('fill-opacity', 0.8)
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.6).toString(); } catch(e) { return '#c084fc'; } })
            .attr('stroke-width', 2);

          // Owner label inside hexagon
          node.filter(function(d) { return d.type === 'owner'; }).append('text')
            .attr('class', 'perf-mm-label perf-mm-label--owner').attr('text-anchor', 'middle')
            .attr('dy', 4).attr('fill', '#1a1a2e').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { var n = d.label || ''; return n.length > 12 ? n.substring(0, 10) + '..' : n; });

          // Secondary pillar dot for multi-pillar ANSTRAT nodes
          var pillarColors = {};
          (graphData.pillarInfo || []).forEach(function(p) { pillarColors[p.id] = p.color; });
          node.filter(function(d) { return d.type === 'anstrat' && d.pillars && d.pillars.length > 1; })
            .each(function(d) {
              var sel = d3.select(this);
              for (var pi = 1; pi < Math.min(d.pillars.length, 4); pi++) {
                var dotColor = pillarColors[d.pillars[pi]] || '#888';
                sel.append('circle')
                  .attr('r', 4)
                  .attr('cx', (d.size || 16) * 2 - 6 - (pi - 1) * 10)
                  .attr('cy', -(d.size || 16) * 1.4 + 4)
                  .attr('fill', dotColor)
                  .attr('stroke', '#111')
                  .attr('stroke-width', 0.5);
              }
            });

          // Inner highlight for competency and root
          node.filter(function(d) { return d.type === 'competency' || d.type === 'root'; })
            .append('circle')
            .attr('r', function(d) { return (d.size || 8) * 0.3; })
            .attr('fill', 'rgba(255,255,255,0.2)')
            .attr('cx', function(d) { return -(d.size || 8) * 0.12; })
            .attr('cy', function(d) { return -(d.size || 8) * 0.12; });

          // Root percentage label
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('class', 'perf-mm-label perf-mm-label--root').attr('text-anchor', 'middle')
            .attr('dy', 5).attr('fill', '#fff').attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });

          // Root quarter label above
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', function(d) { return -d.size - 8; })
            .attr('fill', 'var(--vscode-foreground, #e0e0e0)').attr('font-size', '12px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Pillar labels -- use pillar color, not heat color
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('class', 'perf-mm-label').attr('text-anchor', 'middle')
            .attr('dy', function(d) { return -(d.size || 22) - 8; })
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '11px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Percentage inside pillar ring
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });

          // ANSTRAT labels inside rect
          node.filter(function(d) { return d.type === 'anstrat'; }).append('text')
            .attr('class', 'perf-mm-label').attr('text-anchor', 'middle')
            .attr('dy', 4).attr('fill', '#fff').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          var tooltip = document.getElementById('perfMindmapTooltip');
          setupTooltipAndHighlight(node, link, links, tooltip);

          // Store selections for pillar filter
          perfMmState.nodeSelection = node;
          perfMmState.linkSelection = link;
          perfMmState.allLinks = links;
          perfMmState.glowG = glowG;
          perfMmState.pillarNodes = pillarNodes;

          simulation.on('tick', function() {
            pillarNodes.forEach(function(p, i) {
              d3.select(glowG.selectAll('.perf-mm-heat-glow').nodes()[i])
                .attr('cx', p.x).attr('cy', p.y);
            });
            link.attr('x1', function(d) { return d.source.x; }).attr('y1', function(d) { return d.source.y; })
                .attr('x2', function(d) { return d.target.x; }).attr('y2', function(d) { return d.target.y; });
            node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
          });

          setTimeout(function() { fitPerfMindmap(svg, g, perfMmState.zoom, width, height); }, 1500);
        }

        // ---- Main init ----
        function initPerfMindmap() {
          var dataEl = document.getElementById('perfMindmapData');
          var svgEl = document.getElementById('perfMindmapSvg');
          if (!dataEl || !svgEl) return;

          if (typeof d3 === 'undefined') { setTimeout(initPerfMindmap, 500); return; }

          var graphData;
          try {
            graphData = JSON.parse(dataEl.textContent || '');
            if (!graphData || !graphData.nodes) return;
          } catch (e) { return; }

          var container = document.getElementById('perfMindmapGraph');
          if (!container) return;

          var width = container.clientWidth || 800;
          var height = container.clientHeight || 600;

          var svg = d3.select('#perfMindmapSvg');
          svg.selectAll('g.perf-mm-root').remove();

          var zoomBehavior = d3.zoom().scaleExtent([0.15, 4])
            .on('zoom', function(event) { g.attr('transform', event.transform); });
          svg.call(zoomBehavior);

          var g = svg.append('g').attr('class', 'perf-mm-root');
          perfMmState.svg = svg;
          perfMmState.g = g;
          perfMmState.zoom = zoomBehavior;

          renderCombinedView(graphData, svg, g, container, width, height);
          setupControls(container);
        }

        window._initPerfMindmap = initPerfMindmap;
        setTimeout(initPerfMindmap, 150);
      })();

      // ============ Weighted Competency Mindmap (D3) ============
      (function() {
        var wmState = { simulation: null, svg: null, g: null, zoom: null,
          nodeSelection: null, linkSelection: null, allLinks: null,
          edgeLabelSelection: null };

        function initWeightedMindmap() {
          var dataEl = document.getElementById('wmGraphData');
          var svgEl = document.getElementById('wmSvg');
          if (!dataEl || !svgEl) return;
          if (typeof d3 === 'undefined') { setTimeout(initWeightedMindmap, 500); return; }

          var graphData;
          try {
            graphData = JSON.parse(dataEl.textContent || '');
            if (!graphData || !graphData.nodes) return;
          } catch (e) { return; }

          var container = document.getElementById('wmGraph');
          if (!container) return;

          var width = container.clientWidth || 800;
          var height = container.clientHeight || 600;
          var cx = width / 2, cy = height / 2;

          var svg = d3.select('#wmSvg');
          svg.selectAll('g.wm-root').remove();

          var zoomBehavior = d3.zoom().scaleExtent([0.15, 4])
            .on('zoom', function(event) { rootG.attr('transform', event.transform); });
          svg.call(zoomBehavior);

          var rootG = svg.append('g').attr('class', 'wm-root');
          wmState.svg = svg;
          wmState.g = rootG;
          wmState.zoom = zoomBehavior;

          var nodes = graphData.nodes.map(function(d) { return Object.assign({}, d); });
          var links = graphData.links.map(function(d) { return Object.assign({}, d); });

          // Pre-position nodes radially
          var anstratIdx = 0;
          var anstratTotal = nodes.filter(function(d) { return d.type === 'anstrat'; }).length;
          nodes.forEach(function(d) {
            if (d.type === 'root') { d.x = cx; d.y = cy; }
            else if (d.type === 'pillar') {
              var rad = (d.angle || 0) * Math.PI / 180 - Math.PI / 2;
              d.x = cx + 220 * Math.cos(rad);
              d.y = cy + 220 * Math.sin(rad);
            } else if (d.type === 'competency') {
              var pRad = (d.pillarAngle || 0) * Math.PI / 180 - Math.PI / 2;
              var spread = (Math.random() - 0.5) * 0.5;
              d.x = cx + 360 * Math.cos(pRad + spread);
              d.y = cy + 360 * Math.sin(pRad + spread);
            } else if (d.type === 'anstrat') {
              var aRad = (anstratIdx / Math.max(anstratTotal, 1)) * Math.PI * 2 - Math.PI / 2;
              d.x = cx + 220 * Math.cos(aRad);
              d.y = cy + 220 * Math.sin(aRad);
              anstratIdx++;
            } else if (d.type === 'strategy') {
              var sAngle = Math.random() * Math.PI * 2;
              d.x = cx + 450 * Math.cos(sAngle);
              d.y = cy + 450 * Math.sin(sAngle);
            } else if (d.type === 'owner') {
              var oAngle = Math.random() * Math.PI * 2;
              d.x = cx + 300 * Math.cos(oAngle);
              d.y = cy + 300 * Math.sin(oAngle);
            } else {
              d.x = cx + (Math.random() - 0.5) * 700;
              d.y = cy + (Math.random() - 0.5) * 700;
            }
          });

          var simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(function(d) { return d.id; })
              .distance(function(d) {
                if (d.type === 'evidence') return 200;
                if (d.type === 'pillar_strategy') return 160;
                if (d.type === 'owner_anstrat') return 120;
                var src = typeof d.source === 'object' ? d.source : null;
                var tgt = typeof d.target === 'object' ? d.target : null;
                if (src && src.type === 'root') return 220;
                if (src && src.type === 'pillar' && tgt && tgt.type === 'competency') return 160;
                if (src && src.type === 'anstrat') return 70;
                if (tgt && (tgt.type === 'task' || tgt.type === 'bug' || tgt.type === 'story')) return 45;
                return 90;
              })
              .strength(function(d) {
                if (d.type === 'evidence') return 0.15;
                if (d.type === 'owner_anstrat') return 0.25;
                return 0.45;
              }))
            .force('charge', d3.forceManyBody().strength(function(d) {
              if (d.type === 'root') return -800;
              if (d.type === 'pillar') return -600;
              if (d.type === 'competency') return -120;
              if (d.type === 'anstrat') return -180;
              if (d.type === 'epic') return -80;
              if (d.type === 'strategy') return -60;
              if (d.type === 'owner') return -140;
              return -30;
            }))
            .force('radial_pillar', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }))
            .force('radial_comp', d3.forceRadial(360, cx, cy).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }))
            .force('radial_anstrat', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }))
            .force('radial_strat', d3.forceRadial(450, cx, cy).strength(function(d) { return d.type === 'strategy' ? 0.3 : 0; }))
            .force('radial_owner', d3.forceRadial(300, cx, cy).strength(function(d) { return d.type === 'owner' ? 0.2 : 0; }))
            .force('center_root', d3.forceRadial(0, cx, cy).strength(function(d) { return d.type === 'root' ? 1 : 0; }))
            .force('collision', d3.forceCollide().radius(function(d) {
              if (d.type === 'pillar') return (d.size || 22) + 40;
              if (d.type === 'owner') return (d.size || 18) + 8;
              return (d.size || 8) + 4;
            }))
            .alphaDecay(0.012).velocityDecay(0.35);

          simulation.force('angular_pin', function(alpha) {
            var strength = 0.15 * alpha;
            nodes.forEach(function(d) {
              if (d.type !== 'pillar' || d.angle == null) return;
              var targetRad = d.angle * Math.PI / 180 - Math.PI / 2;
              var tx = cx + 220 * Math.cos(targetRad);
              var ty = cy + 220 * Math.sin(targetRad);
              d.vx += (tx - d.x) * strength;
              d.vy += (ty - d.y) * strength;
            });
          });
          wmState.simulation = simulation;

          // Links
          var link = rootG.append('g').attr('class', 'wm-links').selectAll('line').data(links).enter().append('line')
            .attr('class', function(d) {
              if (d.type === 'evidence') return 'perf-mm-link perf-mm-link--evidence';
              if (d.type === 'pillar_strategy') return 'perf-mm-link perf-mm-link--pillar-strategy';
              if (d.type === 'owner_anstrat') return 'perf-mm-link perf-mm-link--owner';
              return 'perf-mm-link';
            })
            .attr('stroke', function(d) {
              var src = typeof d.source === 'object' ? d.source : null;
              if (d.type === 'evidence') return '#f59e0b';
              if (d.type === 'pillar_strategy') return src ? (src.color || '#888') : '#888';
              if (d.type === 'owner_anstrat') return '#e0e0e0';
              return src ? (src.color || '#555') : '#555';
            })
            .attr('stroke-opacity', function(d) {
              if (d.type === 'evidence') return 0.5;
              if (d.type === 'pillar_strategy') return 0.55;
              if (d.type === 'owner_anstrat') return 0.45;
              return 0.3;
            })
            .attr('stroke-width', function(d) {
              if (d.type === 'evidence') return Math.min((d.weight || 1) * 1.5, 4);
              if (d.type === 'pillar_strategy') return 2.5;
              if (d.type === 'owner_anstrat') return 1.5;
              var src = typeof d.source === 'object' ? d.source : null;
              if (src && src.type === 'root') return 3;
              if (src && src.type === 'pillar') return 2;
              if (src && src.type === 'anstrat') return 1.8;
              return 1;
            })
            .attr('stroke-dasharray', function(d) {
              if (d.type === 'evidence') return '6,4';
              if (d.type === 'pillar_strategy') return '6,3,2,3';
              if (d.type === 'owner_anstrat') return '4,3';
              return 'none';
            });
          wmState.linkSelection = link;
          wmState.allLinks = links;

          // Edge weight labels
          var edgeLabels = rootG.append('g').attr('class', 'wm-edge-labels').selectAll('text')
            .data(links.filter(function(d) { return d.label; })).enter().append('text')
            .attr('class', 'wm-edge-label')
            .attr('text-anchor', 'middle')
            .attr('fill', 'var(--vscode-foreground, #aaa)')
            .attr('font-size', '8px')
            .attr('opacity', 0.7)
            .text(function(d) { return d.label; });
          wmState.edgeLabelSelection = edgeLabels;

          // Nodes
          var node = rootG.append('g').attr('class', 'wm-nodes').selectAll('g').data(nodes).enter().append('g')
            .attr('class', function(d) { return 'perf-mm-node perf-mm-node--' + d.type; })
            .call(d3.drag()
              .on('start', function(event, d) {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x; d.fy = d.y;
              })
              .on('drag', function(event, d) { d.fx = event.x; d.fy = event.y; })
              .on('end', function(event, d) {
                if (!event.active) simulation.alphaTarget(0);
                var stickyEl = document.getElementById('wmSticky');
                if (!(stickyEl && stickyEl.checked)) { d.fx = null; d.fy = null; }
              })
            );

          // Root glow + circle
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('r', function(d) { return (d.size || 30) + 6; })
            .attr('fill', 'none').attr('stroke', '#667eea').attr('stroke-width', 2).attr('stroke-opacity', 0.3);
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('r', function(d) { return d.size || 30; })
            .attr('fill', '#667eea').attr('stroke', '#8b9cf5').attr('stroke-width', 3);

          // Pillar ring
          node.filter(function(d) { return d.type === 'pillar'; })
            .append('circle').attr('r', function(d) { return d.size || 22; })
            .attr('fill', 'none').attr('stroke', function(d) { return d.color; })
            .attr('stroke-width', 3).attr('stroke-opacity', 0.7);

          // Competency circles
          node.filter(function(d) { return d.type === 'competency'; })
            .append('circle').attr('r', function(d) { return d.size || 10; })
            .attr('fill', function(d) { return d.heatColor || d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.heatColor || d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5);

          // ANSTRAT rounded rects
          node.filter(function(d) { return d.type === 'anstrat'; })
            .append('rect')
            .attr('width', function(d) { return (d.size || 16) * 4; })
            .attr('height', function(d) { return (d.size || 16) * 2.8; })
            .attr('x', function(d) { return -(d.size || 16) * 2; })
            .attr('y', function(d) { return -(d.size || 16) * 1.4; })
            .attr('rx', 5).attr('ry', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5).attr('opacity', 0.9);

          // Epic triangles
          node.filter(function(d) { return d.type === 'epic'; })
            .append('polygon')
            .attr('points', function(d) {
              var s = d.size || 10;
              return '0,' + (-s) + ' ' + (s * 0.9) + ',' + (s * 0.7) + ' ' + (-s * 0.9) + ',' + (s * 0.7);
            })
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1);

          // Issue squares
          node.filter(function(d) { return d.type === 'task' || d.type === 'bug' || d.type === 'story'; })
            .append('rect')
            .attr('width', function(d) { return (d.size || 6) * 1.6; })
            .attr('height', function(d) { return (d.size || 6) * 1.6; })
            .attr('x', function(d) { return -(d.size || 6) * 0.8; })
            .attr('y', function(d) { return -(d.size || 6) * 0.8; })
            .attr('rx', 2).attr('ry', 2)
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('fill-opacity', 0.7)
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.3).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 0.8);

          // Strategy diamonds
          node.filter(function(d) { return d.type === 'strategy'; })
            .append('polygon')
            .attr('points', function(d) {
              var s = d.size || 12;
              return '0,' + (-s) + ' ' + s + ',0 0,' + s + ' ' + (-s) + ',0';
            })
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', function(d) { return d.isCovered ? 1.5 : 2; })
            .attr('stroke-dasharray', function(d) { return d.isCovered ? 'none' : '4,2'; })
            .attr('opacity', function(d) { return d.isCovered ? 0.9 : 0.65; });

          // Owner hexagons
          node.filter(function(d) { return d.type === 'owner'; })
            .append('polygon').attr('class', 'perf-mm-hexagon')
            .attr('points', function(d) {
              var s = d.size || 18;
              var pts = [];
              for (var i = 0; i < 6; i++) {
                var a = Math.PI / 3 * i - Math.PI / 6;
                pts.push(Math.round(s * Math.cos(a)) + ',' + Math.round(s * Math.sin(a)));
              }
              return pts.join(' ');
            })
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.4).toString(); } catch(e) { return '#ccc'; } })
            .attr('stroke-width', 2);
          node.filter(function(d) { return d.type === 'owner'; }).append('text')
            .attr('class', 'perf-mm-label perf-mm-label--owner').attr('text-anchor', 'middle')
            .attr('dy', 4).attr('fill', '#1a1a2e').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { var n = d.label || ''; return n.length > 12 ? n.substring(0, 10) + '..' : n; });

          // Root percentage
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 5)
            .attr('fill', '#fff').attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', function(d) { return -d.size - 8; })
            .attr('fill', 'var(--vscode-foreground, #e0e0e0)').attr('font-size', '12px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Pillar labels + pct
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('class', 'perf-mm-label').attr('text-anchor', 'middle')
            .attr('dy', function(d) { return -(d.size || 22) - 8; })
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '11px').attr('font-weight', '600')
            .text(function(d) { return d.label; });
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });

          // ANSTRAT labels
          node.filter(function(d) { return d.type === 'anstrat'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 4)
            .attr('fill', '#fff').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Weight sublabels (persistent, togglable)
          var sublabelGroup = node.append('text')
            .attr('class', 'wm-sublabel')
            .attr('text-anchor', 'middle')
            .attr('fill', 'var(--vscode-foreground, #aaa)')
            .attr('font-size', '7px')
            .attr('opacity', 0.8)
            .attr('dy', function(d) {
              if (d.type === 'root') return (d.size || 30) + 16;
              if (d.type === 'pillar') return (d.size || 22) + 14;
              if (d.type === 'competency') return (d.size || 10) + 12;
              if (d.type === 'anstrat') return (d.size || 16) * 1.4 + 12;
              if (d.type === 'epic') return (d.size || 10) + 14;
              if (d.type === 'strategy') return (d.size || 12) + 14;
              if (d.type === 'owner') return (d.size || 18) + 14;
              return (d.size || 6) * 0.8 + 12;
            })
            .text(function(d) { return d.sublabel || ''; });

          // Tooltip
          var tooltip = document.getElementById('wmTooltip');
          node.on('mouseenter', function(event, d) {
            if (!tooltip) return;
            var lines = ['<b>' + (d.fullLabel || d.label) + '</b>'];
            if (d.summary) lines.push(d.summary);
            if (d.weightInfo) lines.push('<span class="wm-tooltip-weight">' + d.weightInfo + '</span>');
            if (d.percentage != null) lines.push('Score: ' + d.percentage + '%');
            if (d.points != null) lines.push('Points: ' + d.points);
            if (d.evidenceCount != null) lines.push('Evidence: ' + d.evidenceCount + ' events');
            if (d.type === 'owner') {
              if (d.email) lines.push(d.email);
              if (d.issueCount != null) lines.push('ANSTRATs: ' + d.issueCount);
              if (d.linkedCount != null) lines.push('Linked: ' + d.linkedCount);
              if (d.themes && d.themes.length) lines.push('Themes: ' + d.themes.join(', '));
            }
            tooltip.innerHTML = lines.join('<br>');
            tooltip.style.display = 'block';
            tooltip.style.left = (event.offsetX + 12) + 'px';
            tooltip.style.top = (event.offsetY - 10) + 'px';
          })
          .on('mousemove', function(event) {
            if (tooltip) {
              tooltip.style.left = (event.offsetX + 12) + 'px';
              tooltip.style.top = (event.offsetY - 10) + 'px';
            }
          })
          .on('mouseleave', function() { if (tooltip) tooltip.style.display = 'none'; });

          wmState.nodeSelection = node;

          // Controls
          var labelsEl = document.getElementById('wmLabels');
          var weightsEl = document.getElementById('wmWeights');
          if (labelsEl) {
            labelsEl.addEventListener('change', function() {
              var show = labelsEl.checked;
              node.selectAll('.perf-mm-label').attr('opacity', show ? 1 : 0);
            });
          }
          if (weightsEl) {
            weightsEl.addEventListener('change', function() {
              var show = weightsEl.checked;
              sublabelGroup.attr('opacity', show ? 0.8 : 0);
              edgeLabels.attr('opacity', show ? 0.7 : 0);
            });
          }
          var reheatBtn = document.getElementById('wmReheat');
          if (reheatBtn) {
            reheatBtn.addEventListener('click', function() { simulation.alpha(1).restart(); });
          }
          var fitBtn = document.getElementById('wmFit');
          if (fitBtn) {
            fitBtn.addEventListener('click', function() {
              var bounds = rootG.node().getBBox();
              if (!bounds.width || !bounds.height) return;
              var pad = 40;
              var scaleX = width / (bounds.width + pad * 2);
              var scaleY = height / (bounds.height + pad * 2);
              var scale = Math.min(scaleX, scaleY, 2);
              var tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
              var ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
              svg.transition().duration(500).call(
                zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
              );
            });
          }

          // Pillar & type filter checkboxes (live in sibling header div, not inside #wmGraph)
          var wrapper = container.closest('.perf-wm-d3-wrapper') || document;
          var pillarChks = wrapper.querySelectorAll('.wmPillarChk');
          var typeChks = wrapper.querySelectorAll('.wmTypeChk');
          function applyFilters() {
            var activePillars = {};
            pillarChks.forEach(function(el) { if (el.checked) activePillars[el.getAttribute('data-pillar')] = true; });
            var activeTypes = {};
            typeChks.forEach(function(el) {
              if (el.checked) {
                (el.getAttribute('data-types') || '').split(',').forEach(function(t) { activeTypes[t.trim()] = true; });
              }
            });
            function isNodeHidden(n) {
              if (!n || n.type === 'root') return false;
              if (n.type !== 'pillar' && !activeTypes[n.type]) return true;
              if (n.type === 'owner') return false;
              if (n.pillars && n.pillars.length) {
                return !n.pillars.some(function(p) { return activePillars[p]; });
              }
              return false;
            }
            node.attr('display', function(d) { return isNodeHidden(d) ? 'none' : 'inline'; });
            link.attr('display', function(d) {
              var src = typeof d.source === 'object' ? d.source : null;
              var tgt = typeof d.target === 'object' ? d.target : null;
              return (isNodeHidden(src) || isNodeHidden(tgt)) ? 'none' : 'inline';
            });
          }
          pillarChks.forEach(function(el) { el.addEventListener('change', applyFilters); });
          typeChks.forEach(function(el) { el.addEventListener('change', applyFilters); });

          // Tick
          simulation.on('tick', function() {
            link.attr('x1', function(d) { return d.source.x; }).attr('y1', function(d) { return d.source.y; })
                .attr('x2', function(d) { return d.target.x; }).attr('y2', function(d) { return d.target.y; });
            edgeLabels
              .attr('x', function(d) { return (d.source.x + d.target.x) / 2; })
              .attr('y', function(d) { return (d.source.y + d.target.y) / 2 - 3; });
            node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
          });

          // Auto-fit after settling
          setTimeout(function() {
            var bounds = rootG.node().getBBox();
            if (!bounds.width || !bounds.height) return;
            var pad = 40;
            var scaleX = width / (bounds.width + pad * 2);
            var scaleY = height / (bounds.height + pad * 2);
            var scale = Math.min(scaleX, scaleY, 2);
            var tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
            var ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
            svg.transition().duration(500).call(
              zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
            );
          }, 1500);
        }

        window._initWeightedMindmap = initWeightedMindmap;
        setTimeout(initWeightedMindmap, 200);
      })();

      // ============ QC Help Tab (D3 Diagrams) ============
      (function() {
        function initPerfHelp() {
          var dataEl = document.getElementById('perfHelpData');
          if (!dataEl) return;
          var hd;
          try { hd = JSON.parse(dataEl.textContent || '{}'); } catch(e) { return; }
          if (!hd.scopeMultipliers) return;

          initPipeline();
          initPyramid(hd);
          initLevelBars(hd);
          initHeatmap(hd);
          initRadar(hd);
          initCompare(hd);
          initTreemap(hd);
          initCapChart(hd);
          initScoringDAG(hd);
          initSignalFilter();
          initTraceSelector();
        }

        // 1.1 Pipeline Flow
        function initPipeline() {
          var container = document.getElementById('perf-help-pipeline');
          if (!container || container.querySelector('svg')) return;

          var W = container.clientWidth || 700;
          var H = 410;
          var cx = W / 2;
          var svg = d3.select(container).append('svg').attr('width', W).attr('height', H).attr('viewBox', '0 0 ' + W + ' ' + H);

          svg.append('defs').append('marker').attr('id', 'pipeline-arrow').attr('viewBox', '0 0 10 10')
            .attr('refX', 10).attr('refY', 5).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#888');

          var srcW = 84, srcH = 38, srcY = 30, srcCount = 7;
          var srcGap = 10;
          var srcTotalW = srcCount * srcW + (srcCount - 1) * srcGap;
          var srcX0 = cx - srcTotalW / 2;

          var enrW = 156, enrH = 34, enrY = 180, enrCount = 4;
          var enrGap = 12;
          var enrTotalW = enrCount * enrW + (enrCount - 1) * enrGap;
          var enrX0 = cx - enrTotalW / 2;

          var ecY = 105, ecW = 280, ecH = 38;
          var sigY = 256, sigW = 280, sigH = 38;
          var fmY = 320, fmW = 192, fmH = 38;
          var capY = 376, capW = 216, capH = 34;

          var sources = ['Git', 'GitLab', 'GitHub', 'Jira', 'Gmail', 'Calendar', 'GDrive'];
          var enrichments = ['Scope Detection', 'Role Detection', 'Classification', 'Strategy Align'];

          var stages = [];
          sources.forEach(function(label, i) {
            stages.push({ label: label, color: '#60a5fa', x: srcX0 + i * (srcW + srcGap), y: srcY, w: srcW, h: srcH });
          });
          stages.push({ label: 'Event Collection', color: '#a78bfa', x: cx - ecW / 2, y: ecY, w: ecW, h: ecH });
          enrichments.forEach(function(label, i) {
            stages.push({ label: label, color: '#a78bfa', x: enrX0 + i * (enrW + enrGap), y: enrY, w: enrW, h: enrH });
          });
          stages.push({ label: 'Signal Counting (>= 2)', color: '#f59e0b', x: cx - sigW / 2, y: sigY, w: sigW, h: sigH });
          stages.push({ label: 'Score Formula', color: '#10b981', x: cx - fmW / 2, y: fmY, w: fmW, h: fmH });
          stages.push({ label: 'Daily Cap (15/comp)', color: '#ef4444', x: cx - capW / 2, y: capY, w: capW, h: capH });

          stages.forEach(function(s) {
            var g = svg.append('g').attr('class', 'perf-help-pipeline-node');
            g.append('rect').attr('x', s.x).attr('y', s.y).attr('width', s.w).attr('height', s.h)
              .attr('rx', 6).attr('fill', s.color + '22').attr('stroke', s.color).attr('stroke-width', 1.5);
            g.append('text').attr('x', s.x + s.w / 2).attr('y', s.y + s.h / 2).text(s.label);
          });

          function bezier(x1, y1, x2, y2) {
            var my = (y1 + y2) / 2;
            return 'M' + x1 + ',' + y1 + ' C' + x1 + ',' + my + ' ' + x2 + ',' + my + ' ' + x2 + ',' + y2;
          }

          var ecLeft = cx - ecW / 2;
          var ecSpanSrc = ecW / (srcCount + 1);
          var ecSpanEnr = ecW / (enrCount + 1);
          var sigLeft = cx - sigW / 2;
          var sigSpanEnr = sigW / (enrCount + 1);

          sources.forEach(function(_label, i) {
            var sx = srcX0 + i * (srcW + srcGap) + srcW / 2;
            var sy = srcY + srcH;
            var tx = ecLeft + (i + 1) * ecSpanSrc;
            var ty = ecY;
            svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(sx, sy, tx, ty));
          });

          enrichments.forEach(function(_label, i) {
            var sx = ecLeft + (i + 1) * ecSpanEnr;
            var sy = ecY + ecH;
            var tx = enrX0 + i * (enrW + enrGap) + enrW / 2;
            var ty = enrY;
            svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(sx, sy, tx, ty));
          });

          enrichments.forEach(function(_label, i) {
            var sx = enrX0 + i * (enrW + enrGap) + enrW / 2;
            var sy = enrY + enrH;
            var tx = sigLeft + (i + 1) * sigSpanEnr;
            var ty = sigY;
            svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(sx, sy, tx, ty));
          });

          svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(cx, sigY + sigH, cx, fmY));
          svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(cx, fmY + fmH, cx, capY));
        }

        // 1.2 Pyramid
        function initPyramid(hd) {
          var container = document.getElementById('perf-help-pyramid');
          if (!container || container.querySelector('.perf-help-pyramid-tier')) return;

          var tiers = [
            { name: 'Strategy', mult: 10, type: 'Executive Priorities', color: '#dc2626' },
            { name: 'ANSTRAT', mult: 7, type: 'Initiatives', color: '#ea580c' },
            { name: 'Epic', mult: 4, type: 'Epics', color: '#d97706' },
            { name: 'Story', mult: 2, type: 'Stories / Tasks / Bugs', color: '#65a30d' },
            { name: 'Commit', mult: 1, type: 'Git Commits', color: '#0891b2' },
          ];

          tiers.forEach(function(t, i) {
            var widthPct = 24 + (tiers.length - 1 - i) * 12;
            var div = document.createElement('div');
            div.className = 'perf-help-pyramid-tier';
            div.innerHTML = '<div class="perf-help-pyramid-block" style="width:' + widthPct + '%;background:' + t.color + '">' +
              '<div class="perf-help-pyramid-mult">x' + t.mult + '</div>' +
              '<div class="perf-help-pyramid-label">' + t.name + '</div>' +
              '<div class="perf-help-pyramid-type">' + t.type + '</div>' +
            '</div>';
            container.appendChild(div);
          });

          var bonus = document.createElement('div');
          bonus.className = 'perf-help-strategy-bonus';
          bonus.innerHTML = '<strong>Strategy Alignment Bonus:</strong> Events matching executive priorities receive an additional <strong>1.5x</strong> multiplier on top of the scope multiplier.';
          container.appendChild(bonus);
        }

        // 2.1 Level Bars
        function initLevelBars(hd) {
          var container = document.getElementById('perf-help-levels');
          if (!container || container.querySelector('.perf-help-level-bar-row')) return;

          var order = ['ase','se','sse','pse','spse','de','sde','fellow'];
          var maxTarget = hd.baseTarget * 3.75;

          order.forEach(function(lid) {
            var scale = hd.levelScales[lid] || 1.0;
            var effectiveTarget = Math.round(hd.baseTarget * scale);
            var pct = Math.round((effectiveTarget / maxTarget) * 100);
            var isActive = lid === hd.level;
            var summary = hd.levelSummaries[lid] || '';

            var row = document.createElement('div');
            row.className = 'perf-help-level-bar-row';
            row.innerHTML =
              '<div class="perf-help-level-label' + (isActive ? ' active' : '') + '">' + lid.toUpperCase() + '</div>' +
              '<div class="perf-help-level-bar-track" title="' + summary + '">' +
                '<div class="perf-help-level-bar-fill' + (isActive ? ' active' : '') + '" style="width:' + pct + '%">' +
                  '<span class="perf-help-level-bar-text">' + scale + 'x &rarr; ' + effectiveTarget + '</span>' +
                '</div>' +
              '</div>';
            container.appendChild(row);
          });
        }

        // 2.2 Heatmap
        function initHeatmap(hd) {
          var container = document.getElementById('perf-help-heatmap');
          if (!container || container.querySelector('.perf-help-heatmap')) return;

          var rw = hd.roleWeightsAll[hd.level] || {};
          var scopes = ['commit', 'story', 'epic', 'anstrat', 'strategy'];
          var roles = ['reporter', 'assignee', 'contributor'];

          var maxVal = 0;
          scopes.forEach(function(s) { roles.forEach(function(r) {
            var v = (rw[s] || {})[r] || 0;
            if (v > maxVal) maxVal = v;
          }); });

          var grid = document.createElement('div');
          grid.className = 'perf-help-heatmap';
          grid.style.gridTemplateColumns = '80px repeat(3, 1fr)';

          grid.innerHTML = '<div></div>' + roles.map(function(r) {
            return '<div class="perf-help-heatmap-header">' + r.charAt(0).toUpperCase() + r.slice(1) + '</div>';
          }).join('');

          scopes.forEach(function(s) {
            grid.innerHTML += '<div class="perf-help-heatmap-row-label">' + s + '</div>';
            roles.forEach(function(r) {
              var v = (rw[s] || {})[r] || 0;
              var intensity = maxVal > 0 ? v / maxVal : 0;
              var r_c = Math.round(26 + (190 - 26) * (1 - intensity));
              var g_c = Math.round(54 + (227 - 54) * (1 - intensity));
              var b_c = Math.round(93 + (248 - 93) * (1 - intensity));
              var bg = 'rgb(' + r_c + ',' + g_c + ',' + b_c + ')';
              var textColor = intensity > 0.5 ? '#fff' : '#1a365d';
              grid.innerHTML += '<div class="perf-help-heatmap-cell" style="background:' + bg + ';color:' + textColor + '">' + v + '</div>';
            });
          });

          container.appendChild(grid);
        }

        // 2.3 Radar
        function initRadar(hd) {
          var container = document.getElementById('perf-help-radar');
          if (!container || container.querySelector('svg')) return;

          var pw = hd.pillarWeightsAll[hd.level] || {};
          var pillars = Object.keys(hd.pillarColors);
          var n = pillars.length;
          if (n === 0) return;

          var size = 600, cx = size/2, cy = size/2, R = 220;
          var svg = d3.select(container).append('svg').attr('width', size).attr('height', size)
            .attr('viewBox', '0 0 ' + size + ' ' + size);

          var maxW = 0;
          pillars.forEach(function(p) { if ((pw[p] || 0) > maxW) maxW = pw[p]; });
          maxW = Math.max(maxW, 1.5);

          // Grid circles
          [0.25, 0.5, 0.75, 1.0].forEach(function(f) {
            svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', R * f)
              .attr('fill', 'none').attr('stroke', '#333').attr('stroke-width', 0.5);
          });

          // Axes
          var angleStep = (2 * Math.PI) / n;
          pillars.forEach(function(p, i) {
            var angle = -Math.PI/2 + i * angleStep;
            var ex = cx + R * Math.cos(angle);
            var ey = cy + R * Math.sin(angle);
            svg.append('line').attr('x1', cx).attr('y1', cy).attr('x2', ex).attr('y2', ey)
              .attr('stroke', '#444').attr('stroke-width', 0.5);

            var lx = cx + (R + 40) * Math.cos(angle);
            var ly = cy + (R + 40) * Math.sin(angle);
            svg.append('text').attr('x', lx).attr('y', ly)
              .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
              .attr('font-size', '14px').attr('font-weight', '600').attr('fill', hd.pillarColors[p] || '#888')
              .text(p);
          });

          // Polygon
          var points = pillars.map(function(p, i) {
            var angle = -Math.PI/2 + i * angleStep;
            var r = R * ((pw[p] || 0) / maxW);
            return (cx + r * Math.cos(angle)) + ',' + (cy + r * Math.sin(angle));
          }).join(' ');

          svg.append('polygon').attr('points', points)
            .attr('fill', 'var(--rh-red, #ee0000)').attr('fill-opacity', 0.15)
            .attr('stroke', 'var(--rh-red, #ee0000)').attr('stroke-width', 2);

          // Value dots
          pillars.forEach(function(p, i) {
            var angle = -Math.PI/2 + i * angleStep;
            var r = R * ((pw[p] || 0) / maxW);
            var px = cx + r * Math.cos(angle);
            var py = cy + r * Math.sin(angle);
            svg.append('circle').attr('cx', px).attr('cy', py).attr('r', 5)
              .attr('fill', hd.pillarColors[p] || '#888');
            svg.append('text').attr('x', px).attr('y', py - 14)
              .attr('text-anchor', 'middle').attr('font-size', '14px').attr('font-weight', 'bold')
              .attr('fill', hd.pillarColors[p] || '#888').text(pw[p] || 0);
          });
        }

        // 2.4 Level Compare
        function initCompare(hd) {
          var container = document.getElementById('perf-help-compare');
          var radarContainer = document.getElementById('perf-help-compare-radar');
          var select = document.getElementById('perf-help-compare-level');
          if (!container || !select) return;

          function render() {
            container.innerHTML = '';
            var cmpLevel = select.value;
            var myPw = hd.pillarWeightsAll[hd.level] || {};
            var cmpPw = hd.pillarWeightsAll[cmpLevel] || {};
            var myScale = hd.levelScales[hd.level] || 1;
            var cmpScale = hd.levelScales[cmpLevel] || 1;

            var grid = document.createElement('div');
            grid.className = 'perf-help-compare-grid';

            function colHtml(title, levelId, scale, pw) {
              var target = Math.round(hd.baseTarget * scale);
              var html = '<div class="perf-help-compare-col"><h4>' + title + ' (' + levelId.toUpperCase() + ')</h4>';
              html += '<div class="perf-help-compare-stat"><span>Target Scale</span><span>' + scale + 'x &rarr; ' + target + '</span></div>';
              Object.keys(hd.pillarColors).forEach(function(p) {
                html += '<div class="perf-help-compare-stat"><span>' + p.replace('End-to-End', 'E2E') + '</span><span>' + (pw[p] || 0) + '</span></div>';
              });
              html += '</div>';
              return html;
            }

            grid.innerHTML = colHtml('Your Level', hd.level, myScale, myPw) +
                             colHtml('Compare', cmpLevel, cmpScale, cmpPw);

            container.appendChild(grid);

            // Delta summary
            var deltaDiv = document.createElement('div');
            deltaDiv.style.cssText = 'margin-top:10px;display:flex;flex-wrap:wrap;gap:12px;justify-content:center;font-size:11px;';
            Object.keys(hd.pillarColors).forEach(function(p) {
              var diff = ((cmpPw[p] || 0) - (myPw[p] || 0));
              var cls = diff > 0 ? 'up' : diff < 0 ? 'down' : 'same';
              var arrow = diff > 0 ? '\u2191' : diff < 0 ? '\u2193' : '=';
              deltaDiv.innerHTML += '<span class="font-semibold perf-help-compare-delta ' + cls + '">' +
                p.replace('End-to-End', 'E2E') + ': ' + arrow + ' ' + Math.abs(diff).toFixed(1) + '</span>';
            });
            container.appendChild(deltaDiv);

            renderCompareRadar(hd, radarContainer, myPw, cmpPw, hd.level, cmpLevel);
          }

          render();
          select.addEventListener('change', render);
        }

        function renderCompareRadar(hd, container, myPw, cmpPw, myLevel, cmpLevel) {
          if (!container || typeof d3 === 'undefined') return;
          container.innerHTML = '';

          var pillars = Object.keys(hd.pillarColors);
          var n = pillars.length;
          if (n === 0) return;

          var size = 600, cx = size / 2, cy = size / 2, R = 220;
          var svg = d3.select(container).append('svg')
            .attr('width', size).attr('height', size)
            .attr('viewBox', '0 0 ' + size + ' ' + size);

          var maxW = 0;
          pillars.forEach(function(p) {
            var v1 = myPw[p] || 0, v2 = cmpPw[p] || 0;
            if (v1 > maxW) maxW = v1;
            if (v2 > maxW) maxW = v2;
          });
          maxW = Math.max(maxW, 1.5);

          var angleStep = (2 * Math.PI) / n;

          [0.25, 0.5, 0.75, 1.0].forEach(function(f) {
            svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', R * f)
              .attr('fill', 'none').attr('stroke', '#333').attr('stroke-width', 0.5);
          });

          pillars.forEach(function(p, i) {
            var angle = -Math.PI / 2 + i * angleStep;
            var ex = cx + R * Math.cos(angle);
            var ey = cy + R * Math.sin(angle);
            svg.append('line').attr('x1', cx).attr('y1', cy).attr('x2', ex).attr('y2', ey)
              .attr('stroke', '#444').attr('stroke-width', 0.5);

            var lx = cx + (R + 40) * Math.cos(angle);
            var ly = cy + (R + 40) * Math.sin(angle);
            svg.append('text').attr('x', lx).attr('y', ly)
              .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
              .attr('font-size', '14px').attr('font-weight', '600').attr('fill', hd.pillarColors[p] || '#888')
              .text(p.replace('End-to-End ', 'E2E '));
          });

          function polyPoints(pw) {
            return pillars.map(function(p, i) {
              var angle = -Math.PI / 2 + i * angleStep;
              var r = R * ((pw[p] || 0) / maxW);
              return (cx + r * Math.cos(angle)) + ',' + (cy + r * Math.sin(angle));
            }).join(' ');
          }

          svg.append('polygon').attr('points', polyPoints(cmpPw))
            .attr('fill', '#888').attr('fill-opacity', 0.08)
            .attr('stroke', '#888').attr('stroke-width', 1.5)
            .attr('stroke-dasharray', '6,3');

          svg.append('polygon').attr('points', polyPoints(myPw))
            .attr('fill', 'var(--rh-red, #ee0000)').attr('fill-opacity', 0.15)
            .attr('stroke', 'var(--rh-red, #ee0000)').attr('stroke-width', 2);

          pillars.forEach(function(p, i) {
            var angle = -Math.PI / 2 + i * angleStep;

            var r1 = R * ((myPw[p] || 0) / maxW);
            svg.append('circle')
              .attr('cx', cx + r1 * Math.cos(angle)).attr('cy', cy + r1 * Math.sin(angle))
              .attr('r', 4).attr('fill', 'var(--rh-red, #ee0000)');
            svg.append('text')
              .attr('x', cx + r1 * Math.cos(angle)).attr('y', cy + r1 * Math.sin(angle) - 14)
              .attr('text-anchor', 'middle').attr('font-size', '14px').attr('font-weight', 'bold')
              .attr('fill', 'var(--rh-red, #ee0000)').text(myPw[p] || 0);

            var r2 = R * ((cmpPw[p] || 0) / maxW);
            svg.append('circle')
              .attr('cx', cx + r2 * Math.cos(angle)).attr('cy', cy + r2 * Math.sin(angle))
              .attr('r', 3).attr('fill', '#888').attr('stroke', '#fff').attr('stroke-width', 0.5);
          });

          svg.append('text').attr('x', 8).attr('y', size - 8)
            .attr('font-size', '13px').attr('fill', 'var(--rh-red, #ee0000)')
            .text('\u25CF ' + myLevel.toUpperCase());
          svg.append('text').attr('x', 8).attr('y', size - 26)
            .attr('font-size', '13px').attr('fill', '#888')
            .text('\u25CB ' + cmpLevel.toUpperCase() + ' (dashed)');
        }

        // 3.2 Treemap
        function initTreemap(hd) {
          var container = document.getElementById('perf-help-treemap');
          if (!container || container.querySelector('svg') || typeof d3 === 'undefined') return;

          var treeData = { name: 'Score', children: [] };
          var pillarMap = {};
          var comps = hd.competencyData || [];

          comps.forEach(function(c) {
            var cat = c.category || 'Other';
            var pts = c.points || 0;
            if (pts <= 0) pts = 1;
            if (!pillarMap[cat]) pillarMap[cat] = { name: cat, children: [] };
            pillarMap[cat].children.push({ name: c.name || c.id, value: pts });
          });

          if (Object.keys(pillarMap).length === 0) {
            Object.keys(hd.pillarColors).forEach(function(p) {
              pillarMap[p] = { name: p, children: [{ name: p + ' (no data)', value: 1 }] };
            });
          }

          Object.keys(pillarMap).forEach(function(p) {
            treeData.children.push(pillarMap[p]);
          });

          var W = container.clientWidth || 600;
          var H = 250;
          var svg = d3.select(container).append('svg').attr('width', W).attr('height', H);

          var root = d3.hierarchy(treeData).sum(function(d) { return d.value || 0; }).sort(function(a, b) { return b.value - a.value; });
          d3.treemap().size([W, H]).padding(2)(root);

          var cell = svg.selectAll('g').data(root.leaves()).enter().append('g')
            .attr('class', 'perf-help-treemap-cell')
            .attr('transform', function(d) { return 'translate(' + d.x0 + ',' + d.y0 + ')'; });

          cell.append('rect')
            .attr('width', function(d) { return Math.max(0, d.x1 - d.x0); })
            .attr('height', function(d) { return Math.max(0, d.y1 - d.y0); })
            .attr('rx', 3)
            .attr('fill', function(d) {
              var parent = d.parent ? d.parent.data.name : '';
              return hd.pillarColors[parent] || '#555';
            })
            .attr('fill-opacity', 0.7);

          cell.append('text')
            .attr('x', 4).attr('y', 14)
            .text(function(d) {
              var w = d.x1 - d.x0;
              if (w < 40) return '';
              var t = d.data.name;
              return t.length > Math.floor(w / 6) ? t.substring(0, Math.floor(w / 6) - 2) + '..' : t;
            });

          cell.append('text')
            .attr('x', 4).attr('y', 26).attr('font-size', '9px').attr('fill-opacity', 0.7)
            .text(function(d) { return (d.x1 - d.x0) > 50 ? d.value + ' pts' : ''; });
        }

        // 3.3 Cap Impact
        function initCapChart(hd) {
          var container = document.getElementById('perf-help-cap');
          if (!container || container.querySelector('.perf-help-level-bar-row')) return;

          var comps = hd.competencyData || [];
          if (comps.length === 0) {
            var msgDiv = document.createElement('div');
            msgDiv.className = 'perf-help-empty';
            msgDiv.textContent = 'Cap impact analysis requires daily event data. Use Collect or Backfill to populate, then return here.';
            container.appendChild(msgDiv);
            return;
          }

          var target = Math.round(hd.baseTarget * (hd.levelScales[hd.level] || 1.25));

          comps.forEach(function(c) {
            var pts = c.points || 0;
            var label = c.name || c.id;
            var pct = target > 0 ? Math.min(Math.round(pts / target * 100), 100) : 0;
            var color = pct >= 75 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#ef4444';

            var row = document.createElement('div');
            row.className = 'perf-help-level-bar-row';
            row.innerHTML =
              '<div class="perf-help-level-label perf-help-level-label-wide">' + (label.length > 24 ? label.substring(0,22) + '..' : label) + '</div>' +
              '<div class="perf-help-level-bar-track">' +
                '<div class="perf-help-level-bar-fill" style="width:' + pct + '%;background:' + color + '">' +
                  '<span class="perf-help-level-bar-text">' + pts + '/' + target + ' (' + pct + '%)</span>' +
                '</div>' +
              '</div>';
            container.appendChild(row);
          });
        }

        // 1.3 Interactive Scoring DAG
        function initScoringDAG(hd) {
          var container = document.getElementById('perf-help-dag');
          if (!container || container.querySelector('svg')) return;

          var compSel = document.getElementById('dag-comp');
          var scopeSel = document.getElementById('dag-scope');
          var roleSel = document.getElementById('dag-role');
          var stratSel = document.getElementById('dag-strat');
          var sigSlider = document.getElementById('dag-signals');
          var sigVal = document.getElementById('dag-signals-val');
          if (!compSel || !scopeSel || !roleSel || !stratSel || !sigSlider) return;

          var W = container.clientWidth || 700;
          var H = 320;
          var svg = d3.select(container).append('svg')
            .attr('width', W).attr('height', H)
            .attr('viewBox', '0 0 ' + W + ' ' + H);

          svg.append('defs').append('marker').attr('id', 'dag-arrow')
            .attr('viewBox', '0 0 10 10').attr('refX', 10).attr('refY', 5)
            .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#888');

          svg.append('defs').append('marker').attr('id', 'dag-arrow-green')
            .attr('viewBox', '0 0 10 10').attr('refX', 10).attr('refY', 5)
            .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#10b981');

          svg.append('defs').append('marker').attr('id', 'dag-arrow-red')
            .attr('viewBox', '0 0 10 10').attr('refX', 10).attr('refY', 5)
            .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#ef4444');

          var nodeW = 96, nodeH = 52;
          var mainY = H / 2 - nodeH / 2;
          var gatedY = mainY + 90;
          var padL = 10;
          var gap = (W - padL * 2 - nodeW * 8) / 7;
          if (gap < 12) gap = 12;

          function nx(col) { return padL + col * (nodeW + gap); }

          var nodeDefs = [
            { id: 'event',   col: 0, y: mainY,  color: '#60a5fa', label: 'Work Event',    type: 'input' },
            { id: 'gate',    col: 1, y: mainY,  color: '#f59e0b', label: 'Signal Gate',   type: 'gate' },
            { id: 'base',    col: 2, y: mainY,  color: '#60a5fa', label: 'base_points',   type: 'mult' },
            { id: 'scope',   col: 3, y: mainY,  color: '#a78bfa', label: 'scope',         type: 'mult' },
            { id: 'role',    col: 4, y: mainY,  color: '#a78bfa', label: 'role',           type: 'mult' },
            { id: 'pillar',  col: 5, y: mainY,  color: '#a78bfa', label: 'pillar',         type: 'mult' },
            { id: 'strat',   col: 6, y: mainY,  color: '#a78bfa', label: 'strategy',       type: 'mult' },
            { id: 'raw',     col: 7, y: mainY - 30, color: '#10b981', label: 'Raw Score',  type: 'output' },
            { id: 'cap',     col: 7, y: mainY + 30, color: '#10b981', label: 'Final',      type: 'output' },
            { id: 'gated',   col: 2, y: gatedY, color: '#ef4444', label: 'Blocked',        type: 'dead' },
          ];

          var edgeDefs = [
            { from: 'event', to: 'gate',   path: 'main' },
            { from: 'gate',  to: 'base',   path: 'pass' },
            { from: 'gate',  to: 'gated',  path: 'fail' },
            { from: 'base',  to: 'scope',  path: 'pass' },
            { from: 'scope', to: 'role',   path: 'pass' },
            { from: 'role',  to: 'pillar', path: 'pass' },
            { from: 'pillar',to: 'strat',  path: 'pass' },
            { from: 'strat', to: 'raw',    path: 'pass' },
            { from: 'raw',   to: 'cap',    path: 'cap' },
          ];

          function nodeById(id) {
            for (var i = 0; i < nodeDefs.length; i++) {
              if (nodeDefs[i].id === id) return nodeDefs[i];
            }
            return null;
          }

          function edgePath(fromN, toN) {
            var x1 = nx(fromN.col) + nodeW;
            var y1 = fromN.y + nodeH / 2;
            var x2 = nx(toN.col);
            var y2 = toN.y + nodeH / 2;
            if (fromN.col === toN.col) {
              x1 = nx(fromN.col) + nodeW / 2;
              x2 = nx(toN.col) + nodeW / 2;
              y1 = fromN.y + nodeH;
              y2 = toN.y;
            }
            var mx = (x1 + x2) / 2;
            return 'M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' + x2 + ',' + y2;
          }

          var edgeGroup = svg.append('g').attr('class', 'dag-edges');
          var nodeGroup = svg.append('g').attr('class', 'dag-nodes');
          var labelGroup = svg.append('g').attr('class', 'dag-labels');

          var edgeEls = {};
          edgeDefs.forEach(function(e) {
            var fn = nodeById(e.from);
            var tn = nodeById(e.to);
            if (!fn || !tn) return;
            edgeEls[e.from + '-' + e.to] = edgeGroup.append('path')
              .attr('class', 'dag-edge')
              .attr('d', edgePath(fn, tn))
              .attr('fill', 'none')
              .attr('stroke', '#555')
              .attr('stroke-width', 2)
              .attr('marker-end', 'url(#dag-arrow)');
          });

          var nodeEls = {};
          var valueEls = {};
          var labelEls = {};
          nodeDefs.forEach(function(n) {
            var g = nodeGroup.append('g')
              .attr('transform', 'translate(' + nx(n.col) + ',' + n.y + ')');

            nodeEls[n.id] = g.append('rect')
              .attr('width', nodeW).attr('height', nodeH)
              .attr('rx', 8)
              .attr('fill', n.color + '18')
              .attr('stroke', n.color)
              .attr('stroke-width', 2);

            labelEls[n.id] = g.append('text')
              .attr('x', nodeW / 2).attr('y', 18)
              .attr('text-anchor', 'middle')
              .attr('fill', '#ccc')
              .attr('font-size', '11px')
              .attr('font-weight', '600')
              .text(n.label);

            valueEls[n.id] = g.append('text')
              .attr('x', nodeW / 2).attr('y', 38)
              .attr('text-anchor', 'middle')
              .attr('fill', n.color)
              .attr('font-size', '14px')
              .attr('font-weight', '700')
              .text('');
          });

          var edgeLabelEls = {};
          edgeDefs.forEach(function(e) {
            var fn = nodeById(e.from);
            var tn = nodeById(e.to);
            if (!fn || !tn) return;
            var x1 = nx(fn.col) + nodeW;
            var y1 = fn.y + nodeH / 2;
            var x2 = nx(tn.col);
            var y2 = tn.y + nodeH / 2;
            if (fn.col === tn.col) {
              x1 = nx(fn.col) + nodeW / 2;
              x2 = nx(tn.col) + nodeW / 2;
              y1 = fn.y + nodeH;
              y2 = tn.y;
            }
            edgeLabelEls[e.from + '-' + e.to] = labelGroup.append('text')
              .attr('x', (x1 + x2) / 2)
              .attr('y', (y1 + y2) / 2 - 6)
              .attr('text-anchor', 'middle')
              .attr('fill', '#888')
              .attr('font-size', '10px')
              .text('');
          });

          function update() {
            var opt = compSel.options[compSel.selectedIndex];
            var base = parseInt(opt.getAttribute('data-base') || '3', 10);
            var category = opt.getAttribute('data-category') || 'Technical Contribution';
            var scope = scopeSel.value;
            var role = roleSel.value;
            var aligned = stratSel.value === '1';
            var signals = parseInt(sigSlider.value, 10);
            var minSig = hd.minSignals || 2;

            if (sigVal) sigVal.textContent = '' + signals;

            var scopeMult = hd.scopeMultipliers[scope] || 1;
            var rw = hd.roleWeightsAll[hd.level] || {};
            var roleWeight = (rw[scope] || {})[role] || 1.0;
            var pw = hd.pillarWeightsAll[hd.level] || {};
            var pillarWeight = pw[category] || 1.0;
            var stratBonus = aligned ? 1.5 : 1.0;
            var rawScore = Math.round(base * scopeMult * roleWeight * pillarWeight * stratBonus);
            var cap = hd.dailyCap || 15;
            var capped = rawScore > cap;
            var finalScore = Math.min(rawScore, cap);
            var gated = signals < minSig;

            valueEls['event'].text(signals + ' sig');
            valueEls['gate'].text(signals + ' / ' + minSig);
            valueEls['base'].text(gated ? '-' : base);
            valueEls['scope'].text(gated ? '-' : 'x' + scopeMult);
            valueEls['role'].text(gated ? '-' : roleWeight);
            valueEls['pillar'].text(gated ? '-' : pillarWeight);
            valueEls['strat'].text(gated ? '-' : (aligned ? '1.5x' : '1.0x'));
            valueEls['raw'].text(gated ? '-' : rawScore);
            valueEls['cap'].text(gated ? '0' : finalScore);
            valueEls['gated'].text('0 pts');

            edgeLabelEls['gate-base'].text(gated ? '' : 'pass');
            edgeLabelEls['gate-gated'].text(gated ? 'fail' : '');
            edgeLabelEls['base-scope'].text(gated ? '' : 'x' + scopeMult);
            edgeLabelEls['scope-role'].text(gated ? '' : 'x' + roleWeight);
            edgeLabelEls['role-pillar'].text(gated ? '' : 'x' + pillarWeight);
            edgeLabelEls['pillar-strat'].text(gated ? '' : (aligned ? 'x1.5' : 'x1.0'));
            edgeLabelEls['strat-raw'].text(gated ? '' : '= ' + rawScore);
            edgeLabelEls['raw-cap'].text(!gated && capped ? 'cap ' + cap : '');

            var passColor = '#10b981';
            var failColor = '#ef4444';
            var dimColor = '#333';
            var dimStroke = '#444';

            function setEdge(key, color, width, dash, marker) {
              var e = edgeEls[key];
              if (!e) return;
              e.transition().duration(400)
                .attr('stroke', color)
                .attr('stroke-width', width)
                .attr('stroke-dasharray', dash || null)
                .attr('marker-end', 'url(#' + marker + ')');
            }

            function setNode(id, strokeColor, fillOpacity) {
              var n = nodeEls[id];
              if (!n) return;
              var nd = nodeById(id);
              n.transition().duration(400)
                .attr('stroke', strokeColor)
                .attr('fill', strokeColor + (fillOpacity || '18'));
            }

            setEdge('event-gate', gated ? failColor : passColor, 2.5, null, gated ? 'dag-arrow-red' : 'dag-arrow-green');
            setNode('event', '#60a5fa', '18');
            setNode('gate', gated ? failColor : '#f59e0b', '18');

            var passNodes = ['base', 'scope', 'role', 'pillar', 'strat'];
            var passEdges = ['gate-base', 'base-scope', 'scope-role', 'role-pillar', 'pillar-strat', 'strat-raw'];

            passNodes.forEach(function(id) {
              var nd = nodeById(id);
              if (gated) {
                setNode(id, dimStroke, '08');
                valueEls[id].transition().duration(400).attr('fill', dimColor);
              } else {
                setNode(id, nd.color, '18');
                valueEls[id].transition().duration(400).attr('fill', nd.color);
              }
            });

            passEdges.forEach(function(key) {
              if (gated) {
                setEdge(key, dimStroke, 1, '4,3', 'dag-arrow');
              } else {
                setEdge(key, passColor, 2.5, null, 'dag-arrow-green');
              }
            });

            setEdge('gate-gated', gated ? failColor : dimStroke, gated ? 2.5 : 1, gated ? null : '4,3', gated ? 'dag-arrow-red' : 'dag-arrow');
            setNode('gated', gated ? failColor : dimStroke, gated ? '20' : '08');
            valueEls['gated'].transition().duration(400).attr('fill', gated ? failColor : dimColor);
            labelEls['gated'].transition().duration(400).attr('fill', gated ? '#fca5a5' : dimColor);

            if (!gated) {
              setNode('raw', passColor, '18');
              valueEls['raw'].transition().duration(400).attr('fill', passColor);
              setEdge('raw-cap', capped ? '#f59e0b' : passColor, 2, null, capped ? 'dag-arrow' : 'dag-arrow-green');
              setNode('cap', capped ? '#f59e0b' : passColor, capped ? '20' : '18');
              valueEls['cap'].transition().duration(400).attr('fill', capped ? '#f59e0b' : passColor);
            } else {
              setNode('raw', dimStroke, '08');
              setNode('cap', dimStroke, '08');
              valueEls['raw'].transition().duration(400).attr('fill', dimColor);
              valueEls['cap'].transition().duration(400).attr('fill', dimColor);
              setEdge('raw-cap', dimStroke, 1, '4,3', 'dag-arrow');
            }
          }

          update();
          compSel.addEventListener('change', update);
          scopeSel.addEventListener('change', update);
          roleSel.addEventListener('change', update);
          stratSel.addEventListener('change', update);
          sigSlider.addEventListener('input', update);
        }

        // 1.4 Signal Filter
        function initSignalFilter() {
          var input = document.getElementById('perf-help-signal-filter');
          if (!input) return;
          input.addEventListener('input', function() {
            var query = input.value.toLowerCase();
            document.querySelectorAll('.perf-help-signal-row').forEach(function(row) {
              var searchText = row.getAttribute('data-search') || '';
              row.classList.toggle('hidden', query.length > 0 && searchText.indexOf(query) === -1);
            });
          });
        }

        // 3.1 Event Trace
        function initTraceSelector() {
          var dateSel = document.getElementById('perf-help-trace-date');
          var container = document.getElementById('perf-help-trace');
          if (!dateSel || !container) return;

          dateSel.addEventListener('change', function() {
            var date = dateSel.value;
            if (!date) {
              container.innerHTML = '<div class="perf-help-empty">Select a day above to trace an event.</div>';
              return;
            }
            container.innerHTML = '<div class="perf-help-empty">Loading events for ' + date + '...</div>';
            vscode.postMessage({ command: 'performanceAction', action: 'helpTraceDate', date: date });
          });
        }

        // Listen for trace results
        window.addEventListener('message', function(event) {
          var msg = event.data;
          if (msg && msg.command === 'helpTraceResult' && msg.html) {
            var traceContainer = document.getElementById('perf-help-trace');
            if (traceContainer) traceContainer.innerHTML = msg.html;
          }
          if (msg && msg.command === 'aiAnswer' && msg.answer) {
            var container = document.getElementById('aiAnswerContainer');
            if (container) {
              container.innerHTML = '<div class="ai-answer-card">' +
                msg.answer.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
            }
          }
          if (msg && msg.command === 'missingLinksResult' && msg.suggestions) {
            var mlc = document.getElementById('missingLinksContainer');
            if (mlc) {
              var sug = msg.suggestions;
              if (sug.length === 0) {
                mlc.innerHTML = '';
              } else {
                var mlHtml = '<div class="section"><div class="section-title">Suggested Missing Links <span class="ai-badge">AI</span></div>';
                for (var mi = 0; mi < sug.length; mi++) {
                  var s = sug[mi];
                  mlHtml += '<div class="ai-diff-item"><span class="ai-diff-name">' +
                    (s.issue ? s.issue.key : '') + ': ' + (s.issue ? s.issue.summary : '').substring(0, 60) +
                    '</span><span class="text-secondary text-xs"> &rarr; ' +
                    (s.suggested_anstrat ? s.suggested_anstrat.key : '') + ' (' + (s.similarity * 100).toFixed(0) + '% match)</span></div>';
                }
                mlHtml += '</div>';
                mlc.innerHTML = mlHtml;
              }
            }
          }
          if (msg && msg.command === 'peerGrowthData' && msg.data) {
            var gc = document.getElementById('peerGrowthContainer');
            if (gc) {
              var d = msg.data;
              var html = '';
              var levelColors = { se: '#10b981', pse: '#3b82f6', spse: '#8b5cf6', de: '#f59e0b' };
              var levelLabels = { se: 'Senior', pse: 'Principal', spse: 'Sr Principal', de: 'Distinguished' };
              var userSeries = d.user_series || [];
              if (userSeries.length > 0) {
                var maxPts = 1;
                for (var si = 0; si < userSeries.length; si++) {
                  if (userSeries[si].total_points > maxPts) maxPts = userSeries[si].total_points;
                }
                for (var lk in (d.level_series || {})) {
                  var ls = d.level_series[lk];
                  for (var li = 0; li < ls.length; li++) {
                    if (ls[li].total_points > maxPts) maxPts = ls[li].total_points;
                  }
                }
                var w = 400, h = 80;
                var svg = '<svg viewBox="0 0 ' + w + ' ' + h + '" class="peer-sparkline-svg">';
                function toPath(series, color, dashed) {
                  if (!series || series.length < 2) return '';
                  var pts = [];
                  for (var pi = 0; pi < series.length; pi++) {
                    var x = (pi / (series.length - 1)) * w;
                    var y = h - (series[pi].total_points / maxPts) * (h - 5);
                    pts.push(x.toFixed(1) + ',' + y.toFixed(1));
                  }
                  return '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + color + '" stroke-width="' + (dashed ? '1' : '2') + '"' + (dashed ? ' stroke-dasharray="4,3"' : '') + '/>';
                }
                svg += toPath(userSeries, '#667eea', false);
                for (var lk2 in (d.level_series || {})) {
                  svg += toPath(d.level_series[lk2], levelColors[lk2] || '#888', true);
                }
                svg += '</svg>';
                var legend = '<div class="peer-sparkline-legend"><span class="peer-spark-leg"><span style="background:#667eea" class="peer-spark-dot"></span>You</span>';
                for (var lk3 in (d.level_series || {})) {
                  legend += '<span class="peer-spark-leg"><span style="background:' + (levelColors[lk3] || '#888') + '" class="peer-spark-dot"></span>' + (levelLabels[lk3] || lk3) + '</span>';
                }
                legend += '</div>';
                html = svg + legend;
              } else {
                html = '<div class="text-secondary text-sm">No daily data available for growth trajectory.</div>';
              }
              gc.innerHTML = html;
            }
          }
          if (msg && (msg.command === 'peerBackfillStarted' || msg.command === 'peerBackfillProgress' || msg.command === 'peerBackfillComplete' || msg.command === 'peerBackfillCancelled')) {
            var pbEl = document.getElementById('peerBackfillProgress');
            var pbPct = document.getElementById('peerProgressPct');
            var pbText = document.getElementById('peerProgressText');
            var pbElapsed = document.getElementById('peerProgressElapsed');
            var pbTitle = document.getElementById('peerProgressTitle');
            var cancelBtn = document.getElementById('backfillCancelBtn');
            var allPhaseSegs = document.querySelectorAll('.backfill-phase-segment');
            var allPhaseLabels = document.querySelectorAll('.backfill-phase-labels span');

            function updatePhaseBar(pr) {
              var phases = ['resolve_github', 'prefetch', 'index_gdrive', 'index_meetings', 'collecting', 'benchmarks'];
              var completed = pr.phases_completed || [];
              var current = pr.phase || '';
              allPhaseSegs.forEach(function(seg) {
                var ph = seg.getAttribute('data-phase');
                seg.classList.remove('phase-done', 'phase-active', 'phase-pending');
                if (completed.indexOf(ph) >= 0) {
                  seg.classList.add('phase-done');
                } else if (ph === current) {
                  seg.classList.add('phase-active');
                } else {
                  seg.classList.add('phase-pending');
                }
              });
              allPhaseLabels.forEach(function(lbl) {
                var ph = lbl.getAttribute('data-phase');
                lbl.classList.remove('label-done', 'label-active');
                if (completed.indexOf(ph) >= 0) lbl.classList.add('label-done');
                else if (ph === current) lbl.classList.add('label-active');
              });
            }

            if (pbEl) {
              if (msg.command === 'peerBackfillStarted') {
                pbEl.classList.remove('hidden');
                pbEl.classList.remove('backfill-complete', 'backfill-cancelled');
                if (pbPct) pbPct.textContent = '0%';
                if (pbText) pbText.textContent = 'Starting backfill...';
                if (pbElapsed) pbElapsed.textContent = '';
                if (cancelBtn) cancelBtn.style.display = 'inline-block';
                allPhaseSegs.forEach(function(s) { s.classList.remove('phase-done', 'phase-active'); s.classList.add('phase-pending'); });
              } else if (msg.command === 'peerBackfillProgress' && msg.progress) {
                pbEl.classList.remove('hidden');
                var pr = msg.progress;
                var pctVal = (pr.total_peers > 0 && pr.total_days > 0)
                  ? Math.round(((pr.completed_peers * pr.total_days + pr.completed_days) / (pr.total_peers * pr.total_days)) * 100)
                  : 0;
                if (pbPct) pbPct.textContent = Math.min(pctVal, 100) + '%';
                updatePhaseBar(pr);
                if (pbText) {
                  var filterNote = (pr.filter_info && pr.filter_info !== 'all') ? ' [' + pr.filter_info + ']' : '';
                  var txt = '';
                  if (pr.phase === 'collecting' && pr.current_peer) {
                    txt = pr.current_peer;
                    if (pr.current_level) txt += ' (' + pr.current_level.toUpperCase() + ')';
                    txt += ' — ' + pr.completed_peers + '/' + pr.total_peers + ' peers';
                  } else if (pr.phase_detail) {
                    txt = pr.phase_detail;
                  } else if (pr.current_peer) {
                    txt = pr.current_peer;
                  } else {
                    txt = 'Preparing...';
                  }
                  txt += filterNote;
                  pbText.textContent = txt;
                }
                if (pbElapsed && pr.elapsed_seconds > 0) {
                  var m = Math.floor(pr.elapsed_seconds / 60);
                  var s = pr.elapsed_seconds % 60;
                  pbElapsed.textContent = m > 0 ? m + 'm ' + s + 's' : s + 's';
                }
              } else if (msg.command === 'peerBackfillComplete') {
                var pc = msg.progress || {};
                var completeFilter = (pc.filter_info && pc.filter_info !== 'all') ? ' [' + pc.filter_info + ']' : '';
                pbEl.classList.add('backfill-complete');
                if (pbPct) pbPct.textContent = '100%';
                if (cancelBtn) cancelBtn.style.display = 'none';
                updatePhaseBar({ phases_completed: ['resolve_github','prefetch','index_gdrive','index_meetings','collecting','benchmarks'], phase: 'complete' });
                if (pbText) {
                  pbText.textContent = 'Complete: ' +
                    (pc.completed_peers || 0) + ' peers, ' +
                    (pc.total_events || 0) + ' events' + completeFilter;
                }
                if (pbElapsed && pc.elapsed_seconds > 0) {
                  var m2 = Math.floor(pc.elapsed_seconds / 60);
                  var s2 = pc.elapsed_seconds % 60;
                  pbElapsed.textContent = m2 > 0 ? m2 + 'm ' + s2 + 's' : s2 + 's';
                }
                setTimeout(function() { if (pbEl) pbEl.classList.add('hidden'); }, 10000);
              } else if (msg.command === 'peerBackfillCancelled') {
                pbEl.classList.add('backfill-cancelled');
                if (pbPct) pbPct.textContent = '--';
                if (cancelBtn) cancelBtn.style.display = 'none';
                if (pbText) pbText.textContent = 'Backfill cancelled';
                setTimeout(function() { if (pbEl) pbEl.classList.add('hidden'); }, 5000);
              }
            }
          }
          if (msg && msg.command === 'toggleBackfillOptions') {
            var bfPanel = document.getElementById('backfillOptionsPanel');
            if (bfPanel) bfPanel.classList.toggle('hidden');
          }
          if (msg && msg.command === 'hideBackfillOptions') {
            var bfPanel2 = document.getElementById('backfillOptionsPanel');
            if (bfPanel2) bfPanel2.classList.add('hidden');
          }
          if (msg && msg.command === 'aiLogCategory' && msg.category) {
            var catSelect = document.getElementById('activityCategory');
            if (catSelect) {
              for (var i = 0; i < catSelect.options.length; i++) {
                if (catSelect.options[i].value.toLowerCase() === msg.category.toLowerCase()) {
                  catSelect.selectedIndex = i;
                  break;
                }
              }
            }
          }
        });

        window._initPerfHelp = initPerfHelp;
        setTimeout(initPerfHelp, 200);
      })();

      // ============ QC Overview Charts (D3) ============
      (function() {
        function initQcOverviewCharts() {
          var dataEl = document.getElementById('qcOverviewChartData');
          if (!dataEl || typeof d3 === 'undefined') return;
          var data;
          try { data = JSON.parse(dataEl.textContent); } catch(e) { return; }
          if (!data) return;

          _renderTrendChart(data);
          _renderHeatmap(data);
          _renderPillarChart(data);
          _renderCoverageDonut(data);
        }

        var tooltip = null;
        function showTip(evt, html) {
          if (!tooltip) tooltip = document.getElementById('qcTooltip');
          if (!tooltip) return;
          tooltip.innerHTML = html;
          tooltip.style.display = 'block';
          tooltip.style.left = (evt.clientX + 12) + 'px';
          tooltip.style.top = (evt.clientY - 28) + 'px';
        }
        function hideTip() {
          if (!tooltip) tooltip = document.getElementById('qcTooltip');
          if (tooltip) tooltip.style.display = 'none';
        }

        function _renderTrendChart(data) {
          var svg = d3.select('#qcTrendChart');
          if (svg.empty()) return;
          svg.selectAll('*').remove();

          var days = data.captured_days || [];
          if (days.length < 2) {
            svg.append('text').attr('x', '50%').attr('y', '50%')
              .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted)')
              .attr('font-size', '12px').text('Not enough data for trend chart');
            return;
          }

          var margin = { top: 20, right: 40, bottom: 30, left: 50 };
          var node = svg.node();
          var containerW = node.parentElement ? node.parentElement.getBoundingClientRect().width : 0;
          var width = (containerW || node.clientWidth || 600) - margin.left - margin.right;
          var height = 180 - margin.top - margin.bottom;
          svg.attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' 180');
          var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

          var cumulative = [];
          var running = 0;
          for (var i = 0; i < days.length; i++) {
            running += days[i].total_points;
            cumulative.push({ dayIdx: i + 1, value: running, date: days[i].date, pts: days[i].total_points });
          }

          var currentTotal = running;
          var overallPct = data.overall_percentage || 0;
          var totalDays = data.total_weekdays || 65;
          var projectedFinal = data.trend && data.trend.projected_final != null ? data.trend.projected_final : null;
          var trendStatus = data.trend ? data.trend.status : 'insufficient_data';

          var trendColor = trendStatus === 'on_track' ? '#10b981' : trendStatus === 'at_risk' ? '#f59e0b' : '#ef4444';

          var pctData = cumulative.map(function(d) {
            return { dayIdx: d.dayIdx, pct: currentTotal > 0 ? Math.round(overallPct * d.value / currentTotal) : 0, date: d.date, pts: d.pts, raw: d.value };
          });

          var xMax = Math.max(totalDays, cumulative.length + 5);
          var x = d3.scaleLinear().domain([1, xMax]).range([0, width]);
          var yMax = Math.max(100, projectedFinal || overallPct, d3.max(pctData, function(d) { return d.pct; }) || 100);
          var y = d3.scaleLinear().domain([0, Math.min(yMax * 1.1, 120)]).range([height, 0]);

          g.append('g').attr('transform', 'translate(0,' + height + ')')
            .call(d3.axisBottom(x).ticks(Math.min(10, xMax / 5)).tickFormat(function(d) { return 'Day ' + d; }))
            .selectAll('text,line,path').attr('stroke', 'var(--text-muted)').attr('fill', 'var(--text-muted)').attr('font-size', '10px');

          g.append('g')
            .call(d3.axisLeft(y).ticks(5).tickFormat(function(d) { return d + '%'; }))
            .selectAll('text,line,path').attr('stroke', 'var(--text-muted)').attr('fill', 'var(--text-muted)').attr('font-size', '10px');

          g.selectAll('.grid-line').data(y.ticks(5)).enter()
            .append('line')
            .attr('x1', 0).attr('x2', width)
            .attr('y1', function(d) { return y(d); }).attr('y2', function(d) { return y(d); })
            .attr('stroke', 'var(--border)').attr('stroke-dasharray', '2,3').attr('opacity', 0.4);

          [60, 80].forEach(function(threshold) {
            if (threshold <= yMax * 1.1) {
              g.append('line')
                .attr('x1', 0).attr('x2', width)
                .attr('y1', y(threshold)).attr('y2', y(threshold))
                .attr('stroke', threshold === 80 ? '#10b981' : '#f59e0b')
                .attr('stroke-dasharray', '4,4').attr('opacity', 0.35);
              g.append('text').attr('x', width + 4).attr('y', y(threshold) + 3)
                .attr('fill', threshold === 80 ? '#10b981' : '#f59e0b')
                .attr('font-size', '9px').text(threshold + '%');
            }
          });

          var area = d3.area()
            .x(function(d) { return x(d.dayIdx); })
            .y0(height)
            .y1(function(d) { return y(d.pct); })
            .curve(d3.curveMonotoneX);

          g.append('path').datum(pctData)
            .attr('d', area)
            .attr('fill', trendColor).attr('opacity', 0.08);

          var line = d3.line()
            .x(function(d) { return x(d.dayIdx); })
            .y(function(d) { return y(d.pct); })
            .curve(d3.curveMonotoneX);

          g.append('path').datum(pctData)
            .attr('d', line)
            .attr('fill', 'none').attr('stroke', trendColor).attr('stroke-width', 2.5);

          if (projectedFinal != null && pctData.length > 0) {
            var lastPt = pctData[pctData.length - 1];
            g.append('line')
              .attr('x1', x(lastPt.dayIdx)).attr('y1', y(lastPt.pct))
              .attr('x2', x(totalDays)).attr('y2', y(Math.min(projectedFinal, yMax * 1.1)))
              .attr('stroke', trendColor).attr('stroke-width', 2)
              .attr('stroke-dasharray', '6,4').attr('opacity', 0.5);

            g.append('circle')
              .attr('cx', x(totalDays)).attr('cy', y(Math.min(projectedFinal, yMax * 1.1)))
              .attr('r', 4).attr('fill', trendColor).attr('opacity', 0.5);
            g.append('text')
              .attr('x', x(totalDays)).attr('y', y(Math.min(projectedFinal, yMax * 1.1)) - 8)
              .attr('text-anchor', 'middle').attr('fill', trendColor)
              .attr('font-size', '10px').attr('font-weight', '600')
              .text(projectedFinal + '%');
          }

          if (pctData.length > 0) {
            var last = pctData[pctData.length - 1];
            g.append('circle')
              .attr('cx', x(last.dayIdx)).attr('cy', y(last.pct))
              .attr('r', 5).attr('fill', trendColor).attr('stroke', 'var(--bg-secondary)').attr('stroke-width', 2);
            g.append('text')
              .attr('x', x(last.dayIdx) + 8).attr('y', y(last.pct) + 4)
              .attr('fill', trendColor).attr('font-size', '11px').attr('font-weight', '700')
              .text(overallPct + '%');
          }

          var bisect = d3.bisector(function(d) { return d.dayIdx; }).left;
          var focus = g.append('g').style('display', 'none');
          focus.append('circle').attr('r', 4).attr('fill', trendColor).attr('stroke', '#fff').attr('stroke-width', 1.5);
          focus.append('line').attr('class', 'focus-line').attr('y1', 0).attr('stroke', 'var(--text-muted)').attr('stroke-dasharray', '2,2').attr('opacity', 0.4);

          svg.append('rect')
            .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')')
            .attr('width', width).attr('height', height)
            .attr('fill', 'transparent')
            .on('mousemove', function(event) {
              var coords = d3.pointer(event, g.node());
              var xDay = x.invert(coords[0]);
              var idx = bisect(pctData, xDay, 1);
              if (idx >= pctData.length) idx = pctData.length - 1;
              if (idx < 0) idx = 0;
              var d0 = pctData[Math.max(0, idx - 1)], d1 = pctData[idx];
              var d = (d1 && Math.abs(xDay - d0.dayIdx) > Math.abs(xDay - d1.dayIdx)) ? d1 : d0;
              if (!d) return;
              focus.style('display', null);
              focus.attr('transform', 'translate(' + x(d.dayIdx) + ',' + y(d.pct) + ')');
              focus.select('.focus-line').attr('y2', height - y(d.pct));
              showTip(event, '<b>' + d.date + '</b> (Day ' + d.dayIdx + ')<br>' + d.pct + '% &bull; +' + d.pts + ' pts');
            })
            .on('mouseleave', function() { focus.style('display', 'none'); hideTip(); });
        }

        function _renderHeatmap(data) {
          var container = document.getElementById('qcHeatmapStrip');
          if (!container) return;
          container.innerHTML = '';

          var days = data.captured_days || [];
          if (days.length === 0) return;

          var maxPts = d3.max(days, function(d) { return d.total_points; }) || 1;

          var allDates = new Set(days.map(function(d) { return d.date; }));
          var first = days[0].date;
          var last = days[days.length - 1].date;
          var cur = new Date(first);
          var end = new Date(last);
          var allWeekdays = [];
          while (cur <= end) {
            var dow = cur.getDay();
            if (dow !== 0 && dow !== 6) {
              allWeekdays.push(cur.toISOString().slice(0, 10));
            }
            cur.setDate(cur.getDate() + 1);
          }

          allWeekdays.forEach(function(dateStr) {
            var cell = document.createElement('div');
            cell.style.width = '12px';
            cell.style.height = '12px';
            cell.style.borderRadius = '2px';
            cell.style.cursor = 'default';
            cell.style.transition = 'transform 0.15s';

            var dayData = days.find(function(d) { return d.date === dateStr; });
            if (dayData) {
              var intensity = Math.min(dayData.total_points / maxPts, 1);
              var alpha = 0.1 + intensity * 0.9;
              cell.style.background = 'rgba(16,185,129,' + alpha.toFixed(2) + ')';
              cell.title = dateStr + ': ' + dayData.total_points + ' pts, ' + dayData.event_count + ' events';
            } else {
              cell.style.background = 'var(--bg-tertiary)';
              cell.title = dateStr + ': no data';
            }

            cell.addEventListener('mouseenter', function(e) {
              cell.style.transform = 'scale(1.6)';
              cell.style.zIndex = '1';
              showTip(e, cell.title);
            });
            cell.addEventListener('mouseleave', function() {
              cell.style.transform = '';
              cell.style.zIndex = '';
              hideTip();
            });

            container.appendChild(cell);
          });
        }

        function _renderPillarChart(data) {
          var svg = d3.select('#qcPillarChart');
          if (svg.empty()) return;
          svg.selectAll('*').remove();

          var pillars = data.pillar_avgs || {};
          var colors = data.pillar_colors || {};
          var summary = data.pillar_summary || {};
          var names = Object.keys(pillars);
          if (names.length === 0) return;

          var margin = { top: 10, right: 60, bottom: 10, left: 160 };
          var node = svg.node();
          var containerW = node.parentElement ? node.parentElement.getBoundingClientRect().width : 0;
          var width = (containerW || node.clientWidth || 600) - margin.left - margin.right;
          var height = 160 - margin.top - margin.bottom;
          svg.attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' 160');
          var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

          var barHeight = Math.min(28, Math.floor(height / names.length) - 8);
          var y = d3.scaleBand().domain(names).range([0, height]).padding(0.25);
          var x = d3.scaleLinear().domain([0, 100]).range([0, width]);

          names.forEach(function(name) {
            var pct = pillars[name] || 0;
            var color = colors[name] || '#888';
            var ps = summary[name] || {};
            var yPos = y(name) + y.bandwidth() / 2;

            g.append('rect')
              .attr('x', 0).attr('y', y(name))
              .attr('width', width).attr('height', y.bandwidth())
              .attr('fill', 'var(--bg-tertiary)').attr('rx', 4);

            g.append('rect')
              .attr('x', 0).attr('y', y(name))
              .attr('width', x(Math.min(pct, 100))).attr('height', y.bandwidth())
              .attr('fill', color).attr('opacity', 0.8).attr('rx', 4);

            g.append('text')
              .attr('x', -8).attr('y', yPos + 1)
              .attr('text-anchor', 'end').attr('fill', 'var(--text-primary)')
              .attr('font-size', '12px').attr('font-weight', '600')
              .text(name);

            g.append('text')
              .attr('x', x(Math.min(pct, 100)) + 6).attr('y', yPos + 1)
              .attr('fill', color).attr('font-size', '12px').attr('font-weight', '700')
              .text(pct + '%');

            if (ps.priority_count > 0) {
              g.append('text')
                .attr('x', width + 8).attr('y', yPos + 1)
                .attr('fill', 'var(--text-muted)').attr('font-size', '10px')
                .text(ps.covered + '/' + ps.priority_count);
            }
          });
        }

        function _renderCoverageDonut(data) {
          var svg = d3.select('#qcCoverageDonut');
          if (svg.empty()) return;
          svg.selectAll('*').remove();

          var cs = data.coverage_summary || {};
          var covered = cs.covered || 0;
          var gaps = cs.gaps || 0;
          var total = covered + gaps;
          if (total === 0) return;
          var pct = cs.coverage_pct || 0;

          var size = 80;
          var radius = size / 2;
          var innerR = radius * 0.6;
          var g = svg.append('g').attr('transform', 'translate(' + radius + ',' + radius + ')');

          var arc = d3.arc().innerRadius(innerR).outerRadius(radius);
          var pie = d3.pie().value(function(d) { return d.value; }).sort(null).padAngle(0.03);

          var slices = pie([
            { label: 'Covered', value: covered, color: '#10b981' },
            { label: 'Gaps', value: gaps, color: '#ef4444' }
          ]);

          g.selectAll('path').data(slices).enter()
            .append('path')
            .attr('d', arc)
            .attr('fill', function(d) { return d.data.color; })
            .attr('opacity', 0.85)
            .on('mouseenter', function(event, d) {
              d3.select(this).attr('opacity', 1);
              showTip(event, d.data.label + ': ' + d.data.value);
            })
            .on('mouseleave', function() {
              d3.select(this).attr('opacity', 0.85);
              hideTip();
            });

          g.append('text')
            .attr('text-anchor', 'middle').attr('dy', '0.1em')
            .attr('fill', pct >= 50 ? '#10b981' : '#ef4444')
            .attr('font-size', '16px').attr('font-weight', '700')
            .text(pct + '%');

          g.append('text')
            .attr('text-anchor', 'middle').attr('dy', '1.4em')
            .attr('fill', 'var(--text-muted)')
            .attr('font-size', '8px')
            .text(covered + '/' + total);
        }

        window._initQcOverviewCharts = initQcOverviewCharts;
        setTimeout(initQcOverviewCharts, 100);
      })();

      // ============ Issues Dashboard Charts (D3) ============
      (function() {
        var TAG_COLORS = {
          worktype: '#3b82f6', quality: '#10b981', domain: '#8b5cf6',
          ops: '#f97316', monitoring: '#ef4444', other: '#6b7280'
        };
        var TAG_CAT_MAP = {
          feat:'worktype', fix:'worktype', refactor:'worktype',
          test:'quality', review:'quality', docs:'quality',
          billing:'domain', auth:'domain', api:'domain', config:'domain', mock:'domain',
          deploy:'ops', pipeline:'ops', 'ci/cd':'ops', release:'ops',
          grafana:'monitoring', monitoring:'monitoring', alert:'monitoring',
          security:'monitoring', performance:'monitoring',
          migration:'ops', integration:'domain'
        };

        function getTagColor(tag) {
          return TAG_COLORS[TAG_CAT_MAP[tag] || 'other'] || TAG_COLORS.other;
        }

        function initIssuesDashboard() {
          var dataEl = document.getElementById('issuesDashboardData');
          if (!dataEl) return;
          if (typeof d3 === 'undefined') { setTimeout(initIssuesDashboard, 500); return; }

          var dd;
          try { dd = JSON.parse(dataEl.textContent || '{}'); } catch(e) { return; }

          initTreemap(dd);
          initDonut(dd);
          initGauge(dd);
          initTagChart(dd);
        }

        function initTreemap(dd) {
          var container = document.getElementById('issuesDashTreemap');
          if (!container || !dd.strategies || !dd.strategies.length) return;

          var w = container.clientWidth;
          var h = container.clientHeight;
          if (!w || w < 50) { setTimeout(function() { initTreemap(dd); }, 300); return; }
          if (!h || h < 40) h = 130;
          container.innerHTML = '';

          var root = { name: 'root', children: dd.strategies.map(function(s) {
            return {
              name: s.key.replace('ANSTRAT-','S-'),
              value: Math.max(s.points, 1),
              fullKey: s.key,
              summary: (s.summary || '').substring(0, 40),
              children: (s.children || []).map(function(e) {
                return { name: e.key, value: Math.max(e.points, 1), summary: (e.summary || '').substring(0, 30) };
              })
            };
          })};

          var hier = d3.hierarchy(root).sum(function(d) { return d.children && d.children.length ? 0 : d.value; });
          d3.treemap().size([w, h]).padding(2).round(true)(hier);

          var svg = d3.select(container).append('svg').attr('width', w).attr('height', h);
          var colorScale = d3.scaleOrdinal(d3.schemeTableau10);

          var leaves = hier.leaves();
          var cells = svg.selectAll('g').data(leaves).enter().append('g')
            .attr('transform', function(d) { return 'translate(' + d.x0 + ',' + d.y0 + ')'; });

          cells.append('rect')
            .attr('width', function(d) { return Math.max(d.x1 - d.x0, 0); })
            .attr('height', function(d) { return Math.max(d.y1 - d.y0, 0); })
            .attr('rx', 2)
            .attr('fill', function(d) {
              var anc = d.parent;
              while (anc && anc.depth > 1) anc = anc.parent;
              return colorScale(anc ? anc.data.name : d.data.name);
            })
            .attr('opacity', 0.8)
            .style('cursor', 'pointer')
            .append('title')
            .text(function(d) { return d.data.name + ': ' + d.value + 'pts' + (d.data.summary ? '\\n' + d.data.summary : ''); });

          cells.each(function(d) {
            var cw = d.x1 - d.x0;
            var ch = d.y1 - d.y0;
            if (cw > 30 && ch > 14) {
              d3.select(this).append('text')
                .attr('x', 3).attr('y', 11)
                .attr('class', 'issues-treemap-label')
                .text(function(dd) {
                  var label = dd.data.name;
                  return label.length > cw / 6 ? label.substring(0, Math.floor(cw / 6)) : label;
                });
            }
          });
        }

        function initDonut(dd) {
          var container = document.getElementById('issuesDashDonut');
          if (!container || !dd.scope_points) return;
          container.innerHTML = '';

          var w = container.clientWidth || 140;
          var h = container.clientHeight || 110;
          var radius = Math.min(w, h) / 2 - 4;

          var data = Object.entries(dd.scope_points).filter(function(e) { return e[1] > 0; });
          if (!data.length) return;

          var scopeColors = { commit: '#3b82f6', story: '#10b981', epic: '#f59e0b', anstrat: '#ef4444', meeting: '#8b5cf6', doc: '#06b6d4' };
          var total = data.reduce(function(s, d) { return s + d[1]; }, 0);

          var svg = d3.select(container).append('svg').attr('width', w).attr('height', h);
          var g = svg.append('g').attr('transform', 'translate(' + w/2 + ',' + h/2 + ')');

          var pie = d3.pie().value(function(d) { return d[1]; }).sort(null);
          var arc = d3.arc().innerRadius(radius * 0.55).outerRadius(radius);

          g.selectAll('path').data(pie(data)).enter().append('path')
            .attr('d', arc)
            .attr('fill', function(d) { return scopeColors[d.data[0]] || '#6b7280'; })
            .attr('opacity', 0.85)
            .append('title')
            .text(function(d) { return d.data[0] + ': ' + d.data[1] + 'pts (' + Math.round(d.data[1]/total*100) + '%)'; });

          g.append('text').attr('class', 'issues-donut-center').attr('dy', '0.35em').text(total);

          var legend = d3.select(container).append('div')
            .style('display', 'flex').style('gap', '8px').style('justify-content', 'center')
            .style('flex-wrap', 'wrap').style('margin-top', '2px');
          data.forEach(function(d) {
            legend.append('span')
              .style('font-size', '11px').style('color', 'var(--text-secondary)')
              .html('<span class="perf-scope-legend-dot" style="background:' + (scopeColors[d[0]] || '#6b7280') + '"></span>' + d[0]);
          });
        }

        function initGauge(dd) {
          var container = document.getElementById('issuesDashGauge');
          if (!container) return;
          container.innerHTML = '';

          var pct = dd.alignment_pct || 0;
          var aligned = dd.aligned_points || 0;
          var unaligned = dd.unaligned_points || 0;

          var barColor = pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--error)';

          container.innerHTML =
            '<div class="issues-gauge-pct">' + pct + '%</div>' +
            '<div class="issues-gauge-label">of points are strategy-aligned</div>' +
            '<div class="issues-gauge-bar"><div class="issues-gauge-fill" style="width:' + pct + '%;background:' + barColor + ';"></div></div>' +
            '<div class="issues-gauge-legend">' +
              '<span><span class="issues-gauge-dot" style="background:' + barColor + '"></span>Aligned: ' + aligned + 'pts</span>' +
              '<span><span class="issues-gauge-dot issues-gauge-dot--other"></span>Other: ' + unaligned + 'pts</span>' +
            '</div>';
        }

        function initTagChart(dd) {
          var container = document.getElementById('issuesDashTags');
          if (!container || !dd.tag_counts) return;
          container.innerHTML = '';

          var tags = Object.entries(dd.tag_counts);
          if (!tags.length) return;
          var maxCount = tags.reduce(function(m, t) { return Math.max(m, t[1]); }, 0) || 1;

          var html = '';
          tags.slice(0, 10).forEach(function(t) {
            var pct = Math.round(t[1] / maxCount * 100);
            html += '<div class="issues-tag-bar-row">' +
              '<span class="issues-tag-bar-label">' + t[0] + '</span>' +
              '<span class="issues-tag-bar-fill" style="width:' + Math.max(pct, 4) + '%;background:' + getTagColor(t[0]) + ';"></span>' +
              '<span class="issues-tag-bar-count">' + t[1] + '</span>' +
            '</div>';
          });
          container.innerHTML = html;
        }

        window._initIssuesDashboard = initIssuesDashboard;
        setTimeout(initIssuesDashboard, 250);
      })();

      // ============ Issues Tag Filter ============
      (function() {
        function setupTagFilter() {
          document.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-action="filterTag"]');
            if (!btn) return;
            var tag = btn.getAttribute('data-tag') || '';

            document.querySelectorAll('.issues-tag-filter-btn').forEach(function(b) {
              b.classList.remove('active');
            });

            if (tag) {
              btn.classList.add('active');
              document.querySelectorAll('.perf-tree-node').forEach(function(node) {
                var nodeTags = (node.getAttribute('data-tags') || '').split(',');
                if (nodeTags.indexOf(tag) >= 0 || node.querySelector('.perf-tree-toggle')) {
                  node.classList.remove('tag-filtered-out');
                } else {
                  node.classList.add('tag-filtered-out');
                }
              });
              document.querySelectorAll('.issue-card').forEach(function(card) {
                var cardTags = (card.getAttribute('data-tags') || '').split(',');
                if (cardTags.indexOf(tag) >= 0) {
                  card.classList.remove('tag-filtered-out');
                } else {
                  card.classList.add('tag-filtered-out');
                }
              });
            } else {
              document.querySelectorAll('.perf-tree-node').forEach(function(node) {
                node.classList.remove('tag-filtered-out');
              });
              document.querySelectorAll('.issue-card').forEach(function(card) {
                card.classList.remove('tag-filtered-out');
              });
            }
          });
        }
        setupTagFilter();
      })();
  `;
}

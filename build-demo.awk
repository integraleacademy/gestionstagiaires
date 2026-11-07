# Keep the demo's branding and illustration in sync with the visitor page.
BEGIN { panel = 0; starts = 0; ends = 0 }
/<!-- main-panel:start -->/ {
    starts++
    while ((getline line < demo) > 0) print line
    close(demo)
    panel = 1
    next
}
/<!-- main-panel:end -->/ { ends++; panel = 0; next }
!panel {
    if ($0 ~ /<title>/) print "  <title>Intégrale Connect · Test de maintenance</title>"
    else print
}
END { if (starts != 1 || ends != 1 || panel) exit 1 }
